"""
Sincronización de operaciones registradas sin conexión (contrato API §6).

Reglas:
- El ``uuid`` del dispositivo es la clave de idempotencia: un reenvío devuelve el resultado guardado
  y no crea nada nuevo (RNF05).
- Cada operación se procesa en su propia transacción: un conflicto o un rechazo no afecta a las
  demás del lote.
- Si el stock central no alcanza, la operación queda en CONFLICTO sin descontar nada; el inventario
  nunca queda negativo (RN21). La resuelve un Encargado o Administrador.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session, selectinload

from app.core.contexto import ROLES_GESTION, ROLES_PERSONAL, Contexto
from app.core.security import registrar_bitacora
from app.models.inventario import Categoria, DetalleOrden, Inventario, Orden, Prenda, Sucursal, VariantePrenda
from app.models.reservas import DetalleReserva, Reserva
from app.models.sync import CONFIRMADA, CONFLICTO, RECHAZADA, TIPO_CAMBIO, TIPO_RESERVA, TIPO_VENTA, OperacionSync
from app.models.usuarios import ROL_ADMIN_EMPRESA, ROL_CLIENTE, Rol, Usuario
from app.schemas.sync import (
    DatosCambioOffline, DatosReservaOffline, DatosVentaOffline, OperacionOffline, ResolverConflicto,
)

logger = logging.getLogger(__name__)

VIGENCIA_CATALOGO_HORAS = 24
TOLERANCIA_TOTAL = 0.01


class Rechazo(Exception):
    """La operación no es válida y no se podrá aplicar nunca (estado final RECHAZADA)."""

    def __init__(self, mensaje: str, detalle: Optional[dict] = None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle


class SinStock(Exception):
    """El stock central no alcanza: la operación queda en CONFLICTO."""

    def __init__(self, faltantes: list[dict]):
        super().__init__("Stock insuficiente")
        self.faltantes = faltantes


# ---------------------------------------------------------------- utilidades
def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _a_utc(fecha: Optional[datetime]) -> Optional[datetime]:
    """Las columnas DateTime guardan UTC sin zona horaria."""
    if fecha is None or fecha.tzinfo is None:
        return fecha
    return fecha.astimezone(timezone.utc).replace(tzinfo=None)


def _iso(fecha: Optional[datetime]) -> Optional[str]:
    return None if fecha is None else fecha.isoformat() + "Z"


def _errores(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]


def resultado(registro: OperacionSync, duplicada: bool = False) -> dict:
    return {
        "uuid": registro.uuid,
        "estado": registro.estado,
        "servidor_id": registro.servidor_id,
        "duplicada": duplicada,
        "mensaje": registro.mensaje,
        "detalle": registro.detalle,
    }


def _limitado_a_sucursal(ctx: Contexto) -> Optional[int]:
    """Cajero y Encargado asignados a una sucursal solo operan en ella; el Administrador en todas."""
    if ctx.rol in ROLES_PERSONAL and ctx.rol != ROL_ADMIN_EMPRESA:
        return ctx.usuario.sucursal_id
    return None


def _puede_ver(ctx: Contexto, registro: OperacionSync) -> bool:
    return ctx.rol in ROLES_GESTION or registro.usuario_id == ctx.usuario.id


# ---------------------------------------------------------------- preparar dispositivo
def catalogo_offline(ctx: Contexto, sucursal_id: Optional[int] = None) -> dict:
    db, usuario = ctx.db, ctx.usuario

    consulta = db.query(Sucursal).filter(Sucursal.activa.is_(True))
    propia = _limitado_a_sucursal(ctx)
    if propia:
        consulta = consulta.filter(Sucursal.id == propia)
    sucursales = consulta.order_by(Sucursal.id).all()
    if sucursal_id is not None:
        sucursales = [s for s in sucursales if s.id == sucursal_id]
        if not sucursales:
            raise HTTPException(status_code=404, detail="Sucursal no encontrada o no autorizada")
    ids_sucursales = [s.id for s in sucursales]

    prendas = db.query(Prenda).options(selectinload(Prenda.variantes)).order_by(Prenda.id).all()
    inventario = (
        db.query(Inventario).filter(Inventario.sucursal_id.in_(ids_sucursales)).order_by(Inventario.id).all()
        if ids_sucursales else []
    )
    clientes = []
    if ctx.rol != ROL_CLIENTE:
        clientes = (
            db.query(Usuario).join(Rol, Usuario.rol_id == Rol.id)
            .filter(Rol.nombre == ROL_CLIENTE, Usuario.activo.isnot(False))
            .order_by(Usuario.nombre_completo).all()
        )

    # CU-19: para cambios sin conexión, el personal recibe las ventas recientes y la política
    posventa = {}
    if ctx.rol != ROL_CLIENTE:
        from app.services import cambio_offline
        posventa = {"politica_devoluciones": cambio_offline.politica_offline(ctx),
                    "ventas_recientes": cambio_offline.ventas_para_cambio(ctx, ids_sucursales)}

    return {
        "generado_en": _iso(_ahora()),
        "vigencia_horas": VIGENCIA_CATALOGO_HORAS,
        "empresa": {"id": ctx.empresa.id, "razon_social": ctx.empresa.razon_social, "slug": ctx.empresa.slug},
        "usuario": {"id": usuario.id, "nombre": usuario.nombre_completo, "rol_nombre": ctx.rol,
                    "sucursal_id": usuario.sucursal_id},
        "sucursales": [{"id": s.id, "nombre": s.nombre, "direccion": s.direccion} for s in sucursales],
        "categorias": [{"id": c.id, "nombre": c.nombre} for c in db.query(Categoria).order_by(Categoria.nombre)],
        "prendas": [
            {
                "id": p.id, "nombre": p.nombre, "descripcion": p.descripcion, "precio_base": p.precio_base,
                "imagen_url": p.imagen_url, "categoria_id": p.categoria_id,
                "variantes": [
                    {"id": v.id, "talla": v.talla, "color": v.color, "codigo_sku": v.codigo_sku}
                    for v in sorted(p.variantes, key=lambda v: v.id)
                ],
            }
            for p in prendas
        ],
        "inventario": [
            {"variante_id": i.variante_id, "sucursal_id": i.sucursal_id, "stock_disponible": i.stock_disponible or 0}
            for i in inventario
        ],
        "clientes": [
            {"id": c.id, "nombre_completo": c.nombre_completo, "email": c.email, "telefono": c.telefono}
            for c in clientes
        ],
        **posventa,
    }


# ---------------------------------------------------------------- aplicar operaciones
def _cantidades(items) -> dict[int, int]:
    """Suma las cantidades por variante (una variante puede repetirse en la operación)."""
    total: dict[int, int] = {}
    for item in items:
        total[item.variante_id] = total.get(item.variante_id, 0) + item.cantidad
    return total


def _variantes(db: Session, items) -> dict[int, VariantePrenda]:
    if any(item.cantidad <= 0 for item in items):
        raise Rechazo("Las cantidades deben ser mayores a cero")
    ids = {item.variante_id for item in items}
    encontradas = {v.id: v for v in db.query(VariantePrenda).filter(VariantePrenda.id.in_(ids))}
    faltan = ids - encontradas.keys()
    if faltan:
        raise Rechazo("Variantes no encontradas en la empresa", {"variantes": sorted(faltan)})
    return encontradas


def _descontar_stock(db: Session, sucursal_id: int, cantidades: dict[int, int]) -> None:
    """Verifica todo el stock con bloqueo de fila (RNF04) y recién entonces descuenta."""
    inventarios, faltantes = {}, []
    for variante_id in sorted(cantidades):  # orden fijo para evitar bloqueos cruzados
        inventario = (
            db.query(Inventario)
            .filter(Inventario.sucursal_id == sucursal_id, Inventario.variante_id == variante_id)
            .with_for_update().first()
        )
        disponible = (inventario.stock_disponible or 0) if inventario else 0
        if disponible < cantidades[variante_id]:
            faltantes.append({"variante_id": variante_id, "solicitado": cantidades[variante_id],
                              "disponible": disponible})
        inventarios[variante_id] = inventario
    if faltantes:
        raise SinStock(faltantes)
    for variante_id, cantidad in cantidades.items():
        inventarios[variante_id].stock_disponible -= cantidad


def _cliente(db: Session, cliente_id: int) -> Usuario:
    cliente = db.get(Usuario, cliente_id)
    if cliente is None:
        raise Rechazo("Cliente no encontrado en la empresa")
    return cliente


def _aplicar_venta(db: Session, registro: OperacionSync, datos: DatosVentaOffline) -> tuple[int, str]:
    if datos.metodo_pago.strip().upper() != "EFECTIVO":
        raise Rechazo("Sin conexión solo se aceptan ventas al contado en efectivo")
    variantes = _variantes(db, datos.items)
    if any(item.precio_unitario < 0 for item in datos.items):
        raise Rechazo("Los precios no pueden ser negativos")
    total = round(sum(item.cantidad * item.precio_unitario for item in datos.items), 2)
    if abs(total - datos.total) > TOLERANCIA_TOTAL:
        raise Rechazo(f"El total informado ({datos.total}) no coincide con la suma de los ítems ({total})")
    cliente = _cliente(db, datos.cliente_id) if datos.cliente_id is not None else None

    _descontar_stock(db, registro.sucursal_id, _cantidades(datos.items))

    orden = Orden(
        nombre_cliente=datos.nombre_cliente or (cliente.nombre_completo if cliente else "Cliente ocasional"),
        correo_cliente=cliente.email if cliente else "N/A",
        telefono_cliente=(cliente.telefono if cliente else None) or "N/A",
        direccion_envio="Venta offline en tienda",
        total=total,
        fecha_orden=registro.creado_en_dispositivo or _ahora(),
        estado="COMPLETADO",
        canal="OFFLINE",
        metodo_pago="EFECTIVO",
        sucursal_id=registro.sucursal_id,
        usuario_id=registro.usuario_id,
        cliente_id=cliente.id if cliente else None,
        uuid_operacion=registro.uuid,
    )
    db.add(orden)
    db.flush()
    for item in datos.items:
        db.add(DetalleOrden(
            orden_id=orden.id, prenda_id=variantes[item.variante_id].prenda_id, variante_id=item.variante_id,
            cantidad=item.cantidad, precio_unitario=item.precio_unitario,
        ))
    return orden.id, "Venta registrada"


def _aplicar_reserva(db: Session, registro: OperacionSync, datos: DatosReservaOffline,
                     registrada_por_cliente: bool) -> tuple[int, str]:
    # Un cliente reserva para sí mismo; el personal debe indicar el cliente.
    if registrada_por_cliente:
        cliente_id = registro.usuario_id
    elif datos.cliente_id is None:
        raise Rechazo("Debe indicar el cliente de la reserva")
    else:
        cliente_id = _cliente(db, datos.cliente_id).id
    _variantes(db, datos.items)

    _descontar_stock(db, registro.sucursal_id, _cantidades(datos.items))

    reserva = Reserva(
        fecha_creacion=registro.creado_en_dispositivo or _ahora(),
        # Hora de la cita en la tienda (hora local, igual que la reserva en línea)
        fecha_visita=datos.fecha_visita.replace(tzinfo=None),
        estado="Pendiente",
        cliente_id=cliente_id,
        sucursal_id=registro.sucursal_id,
        usuario_id=None if registrada_por_cliente else registro.usuario_id,
        uuid_operacion=registro.uuid,
    )
    db.add(reserva)
    db.flush()
    for item in datos.items:
        db.add(DetalleReserva(reserva_id=reserva.id, variante_id=item.variante_id, cantidad=item.cantidad))
    return reserva.id, "Reserva registrada"


def _aplicar(ctx: Contexto, registro: OperacionSync, datos: dict, registrada_por_cliente: bool) -> tuple[int, str]:
    """Valida los datos del tipo de operación y la aplica. Lanza Rechazo o SinStock."""
    db = ctx.db
    try:
        if registro.tipo == TIPO_CAMBIO:
            from app.services.cambio_offline import aplicar_cambio
            return aplicar_cambio(ctx, registro, DatosCambioOffline.model_validate(datos))
        if registro.tipo == TIPO_VENTA:
            return _aplicar_venta(db, registro, DatosVentaOffline.model_validate(datos))
        return _aplicar_reserva(db, registro, DatosReservaOffline.model_validate(datos), registrada_por_cliente)
    except ValidationError as e:
        raise Rechazo("Los datos de la operación son inválidos", {"errores": _errores(e)})


def _validar_cabecera(ctx: Contexto, op: OperacionOffline, tipo: str) -> Sucursal:
    if op.empresa_id != ctx.empresa_id:
        raise Rechazo("La operación pertenece a otra empresa")
    if op.usuario_id != ctx.usuario.id:
        raise Rechazo("La operación fue registrada por otro usuario")
    if tipo not in (TIPO_VENTA, TIPO_RESERVA, TIPO_CAMBIO):
        raise Rechazo(f"Tipo de operación desconocido: {op.tipo}")
    if tipo == TIPO_VENTA and ctx.rol not in ROLES_PERSONAL:
        raise Rechazo("Solo el personal de la empresa puede registrar ventas")
    if tipo == TIPO_CAMBIO and ctx.rol not in ROLES_PERSONAL:
        raise Rechazo("Solo el personal de la empresa puede registrar cambios")
    sucursal = ctx.db.get(Sucursal, op.sucursal_id)
    if sucursal is None:
        raise Rechazo("Sucursal no encontrada en la empresa")
    if not sucursal.activa:
        raise Rechazo("La sucursal está inactiva")
    propia = _limitado_a_sucursal(ctx)
    if propia and propia != sucursal.id:
        raise Rechazo("Solo puede registrar operaciones en su sucursal asignada")
    return sucursal


def _registrar_nueva(ctx: Contexto, op: OperacionOffline, dispositivo_id: Optional[str]) -> OperacionSync:
    tipo = op.tipo.strip().upper()[:20]
    registro = OperacionSync(
        uuid=str(op.uuid), tipo=tipo, usuario_id=ctx.usuario.id, dispositivo_id=dispositivo_id,
        creado_en_dispositivo=_a_utc(op.creado_en), datos=op.model_dump(mode="json"),
        recibido_en=_ahora(), procesado_en=_ahora(),
    )
    try:
        registro.sucursal_id = _validar_cabecera(ctx, op, tipo).id
        registro.servidor_id, registro.mensaje = _aplicar(ctx, registro, op.datos, ctx.rol == ROL_CLIENTE)
        registro.estado = CONFIRMADA
    except Rechazo as r:
        registro.estado, registro.mensaje, registro.detalle = RECHAZADA, r.mensaje[:255], r.detalle
    except SinStock as s:
        registro.estado, registro.mensaje = CONFLICTO, "Stock insuficiente en la sucursal"
        registro.detalle = {"items": s.faltantes}
    ctx.db.add(registro)
    return registro


def _reenvio(ctx: Contexto, uuid: str, empresa_id: str, registro_id: int) -> dict:
    """El uuid ya llegó antes: se devuelve el mismo resultado sin crear nada (RNF05)."""
    registro = ctx.db.get(OperacionSync, registro_id) if empresa_id == ctx.empresa_id else None
    if registro is None or not _puede_ver(ctx, registro):
        # No se revela nada de una operación ajena.
        return {"uuid": uuid, "estado": RECHAZADA, "servidor_id": None, "duplicada": False,
                "mensaje": "El identificador de la operación ya fue utilizado", "detalle": None}
    registro.intentos += 1
    ctx.db.commit()
    return resultado(registro, duplicada=True)


def _buscar_uuid(db: Session, uuid: str):
    """Busca en todas las empresas: el uuid es único en la plataforma."""
    return (
        db.query(OperacionSync.id, OperacionSync.empresa_id)
        .execution_options(sin_tenant=True)
        .filter(OperacionSync.uuid == uuid)
        .first()
    )


def procesar_operacion(ctx: Contexto, op: OperacionOffline, dispositivo_id: Optional[str]) -> dict:
    db, uuid = ctx.db, str(op.uuid)
    previa = _buscar_uuid(db, uuid)
    if previa is not None:
        return _reenvio(ctx, uuid, previa.empresa_id, previa.id)
    try:
        registro = _registrar_nueva(ctx, op, dispositivo_id)
        db.commit()
    except Exception:
        db.rollback()
        previa = _buscar_uuid(db, uuid)  # el mismo uuid llegó en otro envío simultáneo
        if previa is not None:
            return _reenvio(ctx, uuid, previa.empresa_id, previa.id)
        logger.exception("No se pudo procesar la operación offline %s", uuid)
        return {"uuid": uuid, "estado": "ERROR", "servidor_id": None, "duplicada": False,
                "mensaje": "Error temporal del servidor: la operación no se guardó, reintente más tarde",
                "detalle": None}

    if registro.estado == CONFIRMADA:
        tabla = {TIPO_VENTA: "ordenes", TIPO_CAMBIO: "solicitudes_devolucion"}.get(registro.tipo, "reservas")
        registrar_bitacora(db, ctx.usuario.id, f"{registro.tipo}_OFFLINE", tabla, registro.servidor_id,
                           f"Sincronizada desde el dispositivo {registro.dispositivo_id or '-'} ({uuid})")
    return resultado(registro)


def procesar_lote(ctx: Contexto, operaciones: list[OperacionOffline], dispositivo_id: Optional[str]) -> list[dict]:
    # Se aplican en el orden en que ocurrieron en el dispositivo; la respuesta respeta el orden del lote.
    orden = sorted(range(len(operaciones)), key=lambda i: (_a_utc(operaciones[i].creado_en) or datetime.min, i))
    resultados: list[dict] = [{}] * len(operaciones)
    for i in orden:
        resultados[i] = procesar_operacion(ctx, operaciones[i], dispositivo_id)
    return resultados


def consultar_estado(ctx: Contexto, uuids: list[str]) -> list[dict]:
    registros = {r.uuid: r for r in ctx.db.query(OperacionSync).filter(OperacionSync.uuid.in_(uuids))}
    salida = []
    for uuid in uuids:
        registro = registros.get(uuid)
        if registro is None or not _puede_ver(ctx, registro):
            salida.append({"uuid": uuid, "estado": "DESCONOCIDA", "servidor_id": None, "duplicada": False,
                           "mensaje": "El servidor no recibió esta operación", "detalle": None})
        else:
            salida.append(resultado(registro))
    return salida


# ---------------------------------------------------------------- conflictos
def _items_con_stock(db: Session, registro: OperacionSync) -> list[dict]:
    datos = registro.datos.get("datos") or {}
    # En un CAMBIO el conflicto es por las prendas a entregar
    items = datos.get("entregados" if registro.tipo == TIPO_CAMBIO else "items") or []
    ids = {i.get("variante_id") for i in items}
    variantes = {
        v.id: v for v in db.query(VariantePrenda).options(selectinload(VariantePrenda.prenda))
        .filter(VariantePrenda.id.in_(ids))
    }
    stock = {
        i.variante_id: i.stock_disponible or 0
        for i in db.query(Inventario).filter(Inventario.sucursal_id == registro.sucursal_id,
                                             Inventario.variante_id.in_(ids))
    }
    salida = []
    for item in items:
        variante = variantes.get(item.get("variante_id"))
        salida.append({
            "variante_id": item.get("variante_id"),
            "prenda": variante.prenda.nombre if variante and variante.prenda else None,
            "talla": variante.talla if variante else None,
            "color": variante.color if variante else None,
            "cantidad": item.get("cantidad"),
            "precio_unitario": item.get("precio_unitario"),
            "stock_actual": stock.get(item.get("variante_id"), 0),
        })
    return salida


def _vista_conflicto(db: Session, registro: OperacionSync) -> dict:
    datos = registro.datos.get("datos") or {}
    return {
        "uuid": registro.uuid,
        "tipo": registro.tipo,
        "estado": registro.estado,
        "sucursal": {"id": registro.sucursal.id, "nombre": registro.sucursal.nombre} if registro.sucursal else None,
        "usuario": {"id": registro.usuario.id, "nombre": registro.usuario.nombre_completo},
        "creado_en": _iso(registro.creado_en_dispositivo),
        "recibido_en": _iso(registro.recibido_en),
        "mensaje": registro.mensaje,
        "datos": {k: v for k, v in datos.items() if k not in ("items", "entregados")},
        "items": _items_con_stock(db, registro),
    }


def listar_conflictos(ctx: Contexto, sucursal_id: Optional[int] = None) -> list[dict]:
    consulta = ctx.db.query(OperacionSync).filter(OperacionSync.estado == CONFLICTO)
    sucursal_id = _limitado_a_sucursal(ctx) or sucursal_id
    if sucursal_id:
        consulta = consulta.filter(OperacionSync.sucursal_id == sucursal_id)
    return [_vista_conflicto(ctx.db, r) for r in consulta.order_by(OperacionSync.recibido_en).all()]


def _datos_ajustados(registro: OperacionSync, ajuste: list) -> dict:
    """Arma los datos de la operación con las cantidades corregidas por el Encargado/Administrador."""
    original = dict(registro.datos.get("datos") or {})
    originales: dict[int, dict] = {}
    for item in original.get("items") or []:
        previo = originales.setdefault(item["variante_id"], {**item, "cantidad": 0})
        previo["cantidad"] += item["cantidad"]

    vistos = set()
    items = []
    for item in ajuste:
        if item.variante_id in vistos:
            raise HTTPException(status_code=422, detail=f"La variante {item.variante_id} está repetida en el ajuste")
        vistos.add(item.variante_id)
        if item.variante_id not in originales:
            raise HTTPException(status_code=422,
                                detail=f"La variante {item.variante_id} no forma parte de la operación original")
        if item.cantidad > originales[item.variante_id]["cantidad"]:
            raise HTTPException(status_code=422,
                                detail=f"No puede aumentar la cantidad de la variante {item.variante_id}")
        items.append({**originales[item.variante_id], "cantidad": item.cantidad})

    original["items"] = items
    if registro.tipo == TIPO_VENTA:
        original["total"] = round(sum(i["cantidad"] * i["precio_unitario"] for i in items), 2)
    return original


def resolver_conflicto(ctx: Contexto, uuid: str, cuerpo: ResolverConflicto) -> dict:
    db = ctx.db
    registro = db.query(OperacionSync).filter(OperacionSync.uuid == uuid).with_for_update().first()
    if registro is None:
        raise HTTPException(status_code=404, detail="Operación no encontrada")
    propia = _limitado_a_sucursal(ctx)
    if propia and registro.sucursal_id != propia:
        raise HTTPException(status_code=403, detail="Solo puede resolver conflictos de su sucursal")
    if registro.estado != CONFLICTO:
        raise HTTPException(status_code=409, detail=f"La operación no está en conflicto (estado {registro.estado})")

    responsable = ctx.usuario.nombre_completo
    if cuerpo.accion == "RECHAZAR":
        if not (cuerpo.motivo or "").strip():
            raise HTTPException(status_code=422, detail="Indique el motivo del rechazo")
        registro.estado = RECHAZADA
        registro.mensaje = f"Rechazada por {responsable}: {cuerpo.motivo.strip()}"[:255]
    else:
        es_cambio = registro.tipo == TIPO_CAMBIO
        if not es_cambio and not cuerpo.items:
            raise HTTPException(status_code=422, detail="Indique los ítems y cantidades del ajuste")
        sucursal = db.get(Sucursal, registro.sucursal_id)
        if sucursal is None or not sucursal.activa:
            raise HTTPException(status_code=409, detail="La sucursal está inactiva: solo se puede rechazar")
        # Un cambio no se ajusta por cantidades: se reintenta tal cual (por ejemplo, después de reponer stock)
        datos = dict(registro.datos.get("datos") or {}) if es_cambio else _datos_ajustados(registro, cuerpo.items)
        registrada_por_cliente = registro.usuario.rol.nombre == ROL_CLIENTE
        try:
            servidor_id, mensaje = _aplicar(ctx, registro, datos, registrada_por_cliente)
        except SinStock as s:
            db.rollback()
            faltan = ", ".join(
                f"variante {f['variante_id']} (pide {f['solicitado']}, hay {f['disponible']})" for f in s.faltantes
            )
            raise HTTPException(status_code=409, detail=f"El ajuste todavía no alcanza el stock: {faltan}")
        except Rechazo as r:
            db.rollback()
            raise HTTPException(status_code=409, detail=f"{r.mensaje}: solo se puede rechazar")
        registro.estado, registro.servidor_id = CONFIRMADA, servidor_id
        if es_cambio:
            registro.mensaje = f"{mensaje}, reintentado por {responsable}"[:255]
        else:
            registro.mensaje = f"{mensaje} con ajuste de {responsable}"[:255]
            registro.detalle = {"items_confirmados": datos["items"]}

    registro.resolucion = cuerpo.accion
    registro.resuelto_por = ctx.usuario.id
    registro.resuelto_en = registro.procesado_en = _ahora()
    db.commit()
    registrar_bitacora(db, ctx.usuario.id, f"CONFLICTO_{cuerpo.accion}", "operaciones_sync", registro.id,
                       f"{registro.tipo} {registro.uuid}: {registro.mensaje}")
    return resultado(registro)


# ---------------------------------------------------------------- registro (RNF10)
def registro_sync(ctx: Contexto, estado: Optional[str] = None, desde: Optional[datetime] = None,
                  limite: int = 200) -> list[dict]:
    consulta = ctx.db.query(OperacionSync).options(selectinload(OperacionSync.usuario))
    if estado:
        consulta = consulta.filter(OperacionSync.estado == estado.upper())
    if desde:
        consulta = consulta.filter(OperacionSync.recibido_en >= _a_utc(desde))
    return [
        {
            "uuid": r.uuid, "tipo": r.tipo, "estado": r.estado, "sucursal_id": r.sucursal_id,
            "usuario": {"id": r.usuario.id, "nombre": r.usuario.nombre_completo},
            "dispositivo_id": r.dispositivo_id, "creado_en": _iso(r.creado_en_dispositivo),
            "recibido_en": _iso(r.recibido_en), "procesado_en": _iso(r.procesado_en), "intentos": r.intentos,
            "servidor_id": r.servidor_id, "mensaje": r.mensaje, "detalle": r.detalle,
            "resolucion": r.resolucion, "resuelto_por": r.resuelto_por, "resuelto_en": _iso(r.resuelto_en),
        }
        for r in consulta.order_by(OperacionSync.recibido_en.desc()).limit(limite)
    ]
