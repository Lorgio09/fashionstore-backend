"""
Devoluciones y cambios (CU-01 a CU-11) y notas de crédito (CU-07).

Flujo de una solicitud:
    EN_INSPECCION --(CU-03)--> INSPECCIONADA --(CU-04 / CU-05 / CU-06)--> CAMBIO_REALIZADO | REEMBOLSADA
                                     |                                     \\--(CU-08)--> PENDIENTE_STOCK | CERRADA_CON_NOTA
                                     \\--> RECHAZADA
Reglas: la venta debe ser de la empresa (si no, "Venta no encontrada"), estar pagada y dentro del plazo
de la política (el plazo cuenta desde la venta original); no se devuelve más de lo vendido menos lo ya
devuelto; las categorías no retornables solo admiten defecto de fábrica. El stock se ajusta con bloqueo
de fila y cada ajuste queda en movimientos_inventario (CU-10).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_

from app.core.contexto import ROLES_GESTION, ROLES_PERSONAL, Contexto
from app.core.security import registrar_bitacora
from app.models.inventario import DetalleOrden, Inventario, Orden, Prenda, Sucursal, VariantePrenda
from app.models.posventa import (
    CAMBIO_REALIZADO, CERRADA_CON_NOTA, EN_INSPECCION, ESTADOS_FINALES, INSPECCIONADA, PENDIENTE_STOCK, RECHAZADA,
    REEMBOLSADA, DetalleSolicitud, MovimientoInventario, MovimientoNotaCredito, NotaCredito, PoliticaDevolucion,
    SolicitudDevolucion,
)
from app.models.usuarios import ROL_ADMIN_EMPRESA, ROL_CLIENTE, Usuario
from app.services.reportes import catalogo
from app.services.reportes.catalogo import OFFSET_HORAS, fmt_fecha
from app.services.reportes.consultas import VENTAS_VALIDAS

POLITICA_POR_DEFECTO = dict(plazo_cambio_dias=30, plazo_garantia_dias=90, categorias_no_retornables=[],
                            max_cambios_por_prenda=2, max_devoluciones_mes_cliente=3, fuera_de_plazo="RECHAZAR",
                            recargo_pct=0.0, vigencia_nota_credito_dias=180, umbral_diferencia_caja=50.0)
PAGOS_ELECTRONICOS = {"STRIPE", "QR", "TARJETA"}
APTAS = {"APTA", "APTA_CON_DESCUENTO"}
MOTIVOS = {"TALLA": "No le quedó la talla", "AJUSTE_MEDIDA": "Ajuste de medida", "COLOR": "Cambio de color",
           "DEFECTO": "Defecto de fábrica", "PRODUCTO_EQUIVOCADO": "Producto equivocado",
           "YA_NO_LO_DESEA": "Ya no lo desea"}


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _local(utc: datetime):
    return (utc + timedelta(hours=OFFSET_HORAS)).date()


def _iso(d: Optional[datetime]) -> Optional[str]:
    return None if d is None else d.isoformat() + "Z"


def _dinero(v) -> float:
    return round(float(v or 0), 2)


def _gestion(ctx: Contexto) -> bool:
    return ctx.rol in ROLES_GESTION


def _sucursal_propia(ctx: Contexto) -> Optional[int]:
    """Cajero y Encargado operan en su sucursal; el Administrador en todas."""
    return None if ctx.rol == ROL_ADMIN_EMPRESA else ctx.usuario.sucursal_id


# ---------------------------------------------------------------- política (CU-09)
def politica_vigente(ctx: Contexto):
    p = (ctx.db.query(PoliticaDevolucion)
         .filter(PoliticaDevolucion.empresa_id == ctx.empresa_id, PoliticaDevolucion.vigente_desde <= _ahora())
         .order_by(PoliticaDevolucion.vigente_desde.desc(), PoliticaDevolucion.id.desc()).first())
    return p or PoliticaDevolucion(**POLITICA_POR_DEFECTO)


def vista_politica(p) -> dict:
    datos = {k: getattr(p, k) for k in POLITICA_POR_DEFECTO}
    datos["vigente_desde"] = _iso(p.vigente_desde) if p.id else None
    datos["personalizada"] = p.id is not None
    return datos


def guardar_politica(ctx: Contexto, datos: dict) -> dict:
    from app.models.inventario import Categoria
    ids = set(datos["categorias_no_retornables"])
    existentes = {i for (i,) in ctx.db.query(Categoria.id).filter(Categoria.empresa_id == ctx.empresa_id,
                                                                 Categoria.id.in_(ids))} if ids else set()
    if ids - existentes:
        raise HTTPException(status_code=404, detail=f"Categorías no encontradas: {sorted(ids - existentes)}")
    if datos["plazo_garantia_dias"] < datos["plazo_cambio_dias"]:
        raise HTTPException(status_code=422, detail="El plazo de garantía no puede ser menor que el plazo de cambio")
    p = PoliticaDevolucion(**datos, vigente_desde=_ahora(), creado_por=ctx.usuario.id)
    ctx.db.add(p)
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "MODIFICAR", "politicas_devolucion", p.id, "Nueva política de devoluciones")
    return vista_politica(p)


# ---------------------------------------------------------------- ventas elegibles
def _ya_devuelto(ctx: Contexto, detalle_ids: list[int]) -> tuple[dict, dict]:
    """(unidades ya devueltas, cantidad de cambios) por línea de venta, sin contar solicitudes rechazadas."""
    if not detalle_ids:
        return {}, {}
    filas = (ctx.db.query(DetalleSolicitud.detalle_orden_id, DetalleSolicitud.cantidad,
                          SolicitudDevolucion.resolucion_pedida, SolicitudDevolucion.id)
             .join(SolicitudDevolucion, DetalleSolicitud.solicitud_id == SolicitudDevolucion.id)
             .filter(SolicitudDevolucion.empresa_id == ctx.empresa_id, SolicitudDevolucion.estado != RECHAZADA,
                     DetalleSolicitud.detalle_orden_id.in_(detalle_ids)).all())
    devuelto, cambios = {}, {}
    for linea, cantidad, resolucion, _ in filas:
        devuelto[linea] = devuelto.get(linea, 0) + cantidad
        if resolucion.startswith("CAMBIO"):
            cambios[linea] = cambios.get(linea, 0) + 1
    return devuelto, cambios


def vista_venta(ctx: Contexto, orden: Orden, politica=None) -> dict:
    politica = politica or politica_vigente(ctx)
    lineas = (ctx.db.query(DetalleOrden, Prenda, VariantePrenda)
              .join(Prenda, DetalleOrden.prenda_id == Prenda.id)
              .join(VariantePrenda, DetalleOrden.variante_id == VariantePrenda.id)
              .filter(DetalleOrden.orden_id == orden.id).all())
    devuelto, cambios = _ya_devuelto(ctx, [d.id for d, _, _ in lineas])
    fecha = _local(orden.fecha_orden)
    no_retornables = set(politica.categorias_no_retornables or [])
    return {
        "orden_id": orden.id, "fecha": _iso(orden.fecha_orden), "canal": orden.canal, "estado": orden.estado,
        "metodo_pago": orden.metodo_pago, "sucursal_id": orden.sucursal_id,
        "sucursal": orden.sucursal.nombre if orden.sucursal else "Tienda en línea",
        "cliente_id": orden.cliente_id, "nombre_cliente": orden.nombre_cliente, "total": _dinero(orden.total),
        "limite_cambio": (fecha + timedelta(days=politica.plazo_cambio_dias)).isoformat(),
        "limite_garantia": (fecha + timedelta(days=politica.plazo_garantia_dias)).isoformat(),
        "items": [{
            "detalle_orden_id": d.id, "prenda_id": p.id, "prenda": p.nombre, "variante_id": v.id, "talla": v.talla,
            "color": v.color, "cantidad": d.cantidad, "precio_unitario": _dinero(d.precio_unitario),
            "devuelto": devuelto.get(d.id, 0), "elegible": d.cantidad - devuelto.get(d.id, 0),
            "cambios_realizados": cambios.get(d.id, 0), "retornable": p.categoria_id not in no_retornables,
        } for d, p, v in lineas],
    }


def buscar_ventas(ctx: Contexto, orden_id: Optional[int], cliente: Optional[str], limite: int = 20) -> list[dict]:
    if not orden_id and not cliente:
        raise HTTPException(status_code=422, detail="Indique el número de comprobante o un dato del cliente")
    q = ctx.db.query(Orden).filter(Orden.empresa_id == ctx.empresa_id, Orden.estado.in_(VENTAS_VALIDAS))
    if orden_id:
        q = q.filter(Orden.id == orden_id)
    if cliente:
        patron = f"%{cliente.strip()}%"
        q = (q.outerjoin(Usuario, Orden.cliente_id == Usuario.id)
             .filter(or_(Orden.nombre_cliente.ilike(patron), Orden.correo_cliente.ilike(patron),
                         Orden.telefono_cliente.ilike(patron), Usuario.nombre_completo.ilike(patron),
                         Usuario.email.ilike(patron))))
    politica = politica_vigente(ctx)
    return [vista_venta(ctx, o, politica) for o in q.order_by(Orden.fecha_orden.desc()).limit(limite)]


def mis_compras(ctx: Contexto) -> list[dict]:
    politica = politica_vigente(ctx)
    ordenes = (ctx.db.query(Orden).filter(Orden.empresa_id == ctx.empresa_id, Orden.cliente_id == ctx.usuario.id,
                                          Orden.estado.in_(VENTAS_VALIDAS))
               .order_by(Orden.fecha_orden.desc()).limit(50).all())
    return [vista_venta(ctx, o, politica) for o in ordenes]


# ---------------------------------------------------------------- solicitud (CU-01, CU-02)
def _sucursal_activa(ctx: Contexto, sucursal_id: Optional[int]) -> Sucursal:
    s = ctx.db.get(Sucursal, sucursal_id) if sucursal_id else None
    if s is None or not s.activa:
        raise HTTPException(status_code=404, detail="Sucursal receptora no encontrada o inactiva")
    return s


def crear_solicitud(ctx: Contexto, body) -> dict:
    db = ctx.db
    es_cliente = ctx.rol == ROL_CLIENTE
    orden = db.get(Orden, body.orden_id)
    if orden is None or (es_cliente and orden.cliente_id != ctx.usuario.id):
        raise HTTPException(status_code=404, detail="Compra no encontrada" if es_cliente else "Venta no encontrada")
    if orden.estado not in VENTAS_VALIDAS:
        raise HTTPException(status_code=409, detail="La venta no está pagada: no admite devolución")

    if es_cliente or ctx.rol == ROL_ADMIN_EMPRESA:
        sucursal = _sucursal_activa(ctx, body.sucursal_id or (orden.sucursal_id if not es_cliente else None))
    else:
        sucursal = _sucursal_activa(ctx, ctx.usuario.sucursal_id)

    politica = politica_vigente(ctx)
    dias = (catalogo.hoy_local() - _local(orden.fecha_orden)).days
    plazo = politica.plazo_garantia_dias if body.motivo == "DEFECTO" else politica.plazo_cambio_dias
    fuera_de_plazo = dias > plazo
    if fuera_de_plazo and politica.fuera_de_plazo == "RECHAZAR":
        limite = _local(orden.fecha_orden) + timedelta(days=plazo)
        raise HTTPException(status_code=409, detail=f"Fuera de plazo: el cliente tenía hasta el {fmt_fecha(limite)} "
                                                    f"({plazo} días desde la compra).")

    venta = vista_venta(ctx, orden, politica)
    lineas = {i["detalle_orden_id"]: i for i in venta["items"]}
    vistos, detalles, valor = set(), [], 0.0
    for item in body.items:
        if item.detalle_orden_id in vistos:
            raise HTTPException(status_code=422, detail="Una prenda está repetida en la solicitud")
        vistos.add(item.detalle_orden_id)
        linea = lineas.get(item.detalle_orden_id)
        if linea is None:
            raise HTTPException(status_code=404, detail="La prenda indicada no pertenece a esta venta")
        if item.cantidad > linea["elegible"]:
            raise HTTPException(status_code=409, detail=f"{linea['prenda']}: quedan {linea['elegible']} unidad(es) "
                                                        f"elegibles (vendidas {linea['cantidad']}, ya devueltas {linea['devuelto']}).")
        if not linea["retornable"] and body.motivo != "DEFECTO":
            raise HTTPException(status_code=409, detail=f"{linea['prenda']} pertenece a una categoría no retornable: "
                                                        "solo se acepta por defecto de fábrica.")
        if body.resolucion.startswith("CAMBIO") and linea["cambios_realizados"] >= politica.max_cambios_por_prenda:
            raise HTTPException(status_code=409, detail=f"{linea['prenda']} ya alcanzó el máximo de "
                                                        f"{politica.max_cambios_por_prenda} cambio(s).")
        detalles.append(DetalleSolicitud(detalle_orden_id=linea["detalle_orden_id"], prenda_id=linea["prenda_id"],
                                         variante_id=linea["variante_id"], cantidad=item.cantidad,
                                         precio_unitario=linea["precio_unitario"]))
        valor += item.cantidad * linea["precio_unitario"]

    # Máximo de devoluciones del cliente en los últimos 30 días: requiere autorización del Encargado
    cliente_id = orden.cliente_id or (ctx.usuario.id if es_cliente else None)
    requiere = False
    if cliente_id:
        recientes = (db.query(func.count(SolicitudDevolucion.id))
                     .filter(SolicitudDevolucion.empresa_id == ctx.empresa_id, SolicitudDevolucion.cliente_id == cliente_id,
                             SolicitudDevolucion.estado != RECHAZADA,
                             SolicitudDevolucion.creado_en >= _ahora() - timedelta(days=30)).scalar())
        requiere = recientes >= politica.max_devoluciones_mes_cliente

    sol = SolicitudDevolucion(
        orden_id=orden.id, cliente_id=cliente_id, sucursal_id=sucursal.id, usuario_id=ctx.usuario.id,
        canal="EN_LINEA" if es_cliente else "TIENDA", motivo=body.motivo, resolucion_pedida=body.resolucion,
        estado=EN_INSPECCION, creado_en=_ahora(), fuera_de_plazo=fuera_de_plazo,
        recargo=_dinero(valor * politica.recargo_pct / 100) if fuera_de_plazo else 0.0,
        requiere_autorizacion=requiere, autorizado_por=ctx.usuario.id if requiere and _gestion(ctx) else None,
        observacion=body.observacion, valor_devuelto=_dinero(valor), detalles=detalles,
    )
    db.add(sol)
    db.flush()
    sol.codigo = f"DEV-{sol.id:06d}"
    db.commit()
    registrar_bitacora(db, ctx.usuario.id, "INSERTAR", "solicitudes_devolucion", sol.id,
                       f"{sol.codigo}: {MOTIVOS[sol.motivo]}, {sol.resolucion_pedida}")
    return vista(ctx, sol)


# ---------------------------------------------------------------- consulta
def _acciones(ctx: Contexto, sol: SolicitudDevolucion) -> list[str]:
    if ctx.rol == ROL_CLIENTE or sol.estado in ESTADOS_FINALES:
        return []
    pendiente_autorizacion = sol.requiere_autorizacion and not sol.autorizado_por
    if sol.estado == EN_INSPECCION:
        if pendiente_autorizacion:
            return ["AUTORIZAR"] if _gestion(ctx) else []
        return ["INSPECCIONAR"] if _gestion(ctx) else []
    if sol.estado == INSPECCIONADA:
        return ["CAMBIO_VARIANTE", "CAMBIO_PRODUCTO", "REEMBOLSO", "SIN_STOCK"]
    return ["CAMBIO_VARIANTE", "CAMBIO_PRODUCTO", "SIN_STOCK"]   # PENDIENTE_STOCK


def vista(ctx: Contexto, sol: SolicitudDevolucion) -> dict:
    variantes = {v.id: (v, p) for v, p in ctx.db.query(VariantePrenda, Prenda)
                 .join(Prenda, VariantePrenda.prenda_id == Prenda.id)
                 .filter(VariantePrenda.id.in_({d.variante_id for d in sol.detalles}
                                               | {d.variante_entregada_id for d in sol.detalles if d.variante_entregada_id}))}

    def nombre(vid):
        v, p = variantes.get(vid, (None, None))
        return {"variante_id": vid, "prenda": p.nombre if p else None, "talla": v.talla if v else None,
                "color": v.color if v else None}

    nota = sol.nota_credito
    return {
        "codigo": sol.codigo, "estado": sol.estado, "orden_id": sol.orden_id, "canal": sol.canal,
        "cliente": {"id": sol.cliente.id, "nombre": sol.cliente.nombre_completo} if sol.cliente else None,
        "sucursal": {"id": sol.sucursal.id, "nombre": sol.sucursal.nombre},
        "motivo": sol.motivo, "motivo_texto": MOTIVOS.get(sol.motivo, sol.motivo),
        "resolucion_pedida": sol.resolucion_pedida, "creado_en": _iso(sol.creado_en),
        "requiere_autorizacion": sol.requiere_autorizacion, "autorizada": bool(sol.autorizado_por),
        "fuera_de_plazo": sol.fuera_de_plazo, "recargo": _dinero(sol.recargo),
        "inspeccion": sol.inspeccion, "inspeccionado_en": _iso(sol.inspeccionado_en), "observacion": sol.observacion,
        "valor_devuelto": _dinero(sol.valor_devuelto), "monto_a_favor": _dinero(sol.valor_devuelto - sol.recargo),
        "resolucion": sol.resolucion, "monto_reembolsado": _dinero(sol.monto_reembolsado),
        "forma_reembolso": sol.forma_reembolso, "reembolso_pendiente_procesador": sol.reembolso_pendiente_procesador,
        "monto_cobrado": _dinero(sol.monto_cobrado), "forma_cobro": sol.forma_cobro, "entregas": sol.entregas or [],
        "nota_credito": {"codigo": nota.codigo, "monto": _dinero(nota.monto_inicial), "saldo": _dinero(nota.saldo),
                         "vence_en": _iso(nota.vence_en)} if nota else None,
        "cerrado_en": _iso(sol.cerrado_en),
        "items": [{"id": d.id, "detalle_orden_id": d.detalle_orden_id, **nombre(d.variante_id), "cantidad": d.cantidad,
                   "precio_unitario": _dinero(d.precio_unitario),
                   "entregado": nombre(d.variante_entregada_id) if d.variante_entregada_id else None}
                  for d in sol.detalles],
        "acciones": _acciones(ctx, sol),
    }


def cargar(ctx: Contexto, codigo: str, bloquear: bool = False) -> SolicitudDevolucion:
    q = ctx.db.query(SolicitudDevolucion).filter(SolicitudDevolucion.codigo == codigo)
    sol = (q.with_for_update() if bloquear else q).first()
    propia = _sucursal_propia(ctx)
    if (sol is None or (ctx.rol == ROL_CLIENTE and sol.cliente_id != ctx.usuario.id)
            or (ctx.rol != ROL_CLIENTE and propia and sol.sucursal_id != propia)):
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return sol


def listar(ctx: Contexto, estado=None, sucursal_id=None, motivo=None, desde=None, hasta=None, limite=200) -> dict:
    """Historial con filtros e indicadores (CU-11)."""
    q = ctx.db.query(SolicitudDevolucion).filter(SolicitudDevolucion.empresa_id == ctx.empresa_id)
    if ctx.rol == ROL_CLIENTE:
        q = q.filter(SolicitudDevolucion.cliente_id == ctx.usuario.id)
    else:
        sucursal_id = _sucursal_propia(ctx) or sucursal_id
    if sucursal_id:
        q = q.filter(SolicitudDevolucion.sucursal_id == sucursal_id)
    if estado:
        q = q.filter(SolicitudDevolucion.estado == estado.upper())
    if motivo:
        q = q.filter(SolicitudDevolucion.motivo == motivo.upper())
    if desde:
        q = q.filter(SolicitudDevolucion.creado_en >= datetime.combine(desde, datetime.min.time()) - timedelta(hours=OFFSET_HORAS))
    if hasta:
        q = q.filter(SolicitudDevolucion.creado_en < datetime.combine(hasta + timedelta(days=1), datetime.min.time())
                     - timedelta(hours=OFFSET_HORAS))
    solicitudes = q.order_by(SolicitudDevolucion.creado_en.desc()).limit(limite).all()
    por_estado, por_motivo = {}, {}
    for s in solicitudes:
        por_estado[s.estado] = por_estado.get(s.estado, 0) + 1
        por_motivo[s.motivo] = por_motivo.get(s.motivo, 0) + 1
    return {
        "totales": {
            "solicitudes": len(solicitudes),
            "monto_reembolsado": _dinero(sum(s.monto_reembolsado for s in solicitudes)),
            "cambios_realizados": por_estado.get(CAMBIO_REALIZADO, 0),
            "notas_credito_emitidas": _dinero(sum(s.nota_credito.monto_inicial for s in solicitudes if s.nota_credito)),
            "por_estado": por_estado,
            "por_motivo": [{"motivo": m, "motivo_texto": MOTIVOS.get(m, m), "cantidad": c}
                           for m, c in sorted(por_motivo.items(), key=lambda x: -x[1])],
        },
        "solicitudes": [vista(ctx, s) for s in solicitudes],
    }


# ---------------------------------------------------------------- autorización e inspección (CU-03)
def autorizar(ctx: Contexto, codigo: str) -> dict:
    sol = cargar(ctx, codigo, bloquear=True)
    if not sol.requiere_autorizacion or sol.autorizado_por:
        raise HTTPException(status_code=409, detail="La solicitud no tiene una autorización pendiente")
    sol.autorizado_por = ctx.usuario.id
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "AUTORIZAR", "solicitudes_devolucion", sol.id, sol.codigo)
    return vista(ctx, sol)


def inspeccionar(ctx: Contexto, codigo: str, resultado: str, observacion: Optional[str]) -> dict:
    sol = cargar(ctx, codigo, bloquear=True)
    if sol.estado != EN_INSPECCION:
        raise HTTPException(status_code=409, detail=f"La solicitud no está en inspección (estado {sol.estado})")
    if sol.requiere_autorizacion and not sol.autorizado_por:
        raise HTTPException(status_code=409, detail="El cliente superó el máximo mensual de devoluciones: "
                                                    "primero debe autorizarla el Encargado")
    if resultado == "RECHAZAR":
        if not (observacion or "").strip():
            raise HTTPException(status_code=422, detail="Indique el motivo del rechazo")
        sol.estado, sol.cerrado_en, sol.cerrado_por, sol.resolucion = RECHAZADA, _ahora(), ctx.usuario.id, "RECHAZADA"
    else:
        sol.estado, sol.inspeccion = INSPECCIONADA, resultado
    sol.inspeccionado_por, sol.inspeccionado_en = ctx.usuario.id, _ahora()
    if observacion:
        sol.observacion = observacion
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "INSPECCIONAR", "solicitudes_devolucion", sol.id, f"{sol.codigo}: {resultado}")
    return vista(ctx, sol)


# ---------------------------------------------------------------- inventario (CU-10)
def _inventario(ctx: Contexto, sucursal_id: int, variante_id: int) -> Inventario:
    inv = (ctx.db.query(Inventario)
           .filter(Inventario.sucursal_id == sucursal_id, Inventario.variante_id == variante_id)
           .with_for_update().first())
    if inv is None:
        inv = Inventario(sucursal_id=sucursal_id, variante_id=variante_id, stock_disponible=0, stock_reservado=0,
                         stock_no_disponible=0)
        ctx.db.add(inv)
        ctx.db.flush()
    return inv


def _movimiento(ctx: Contexto, sol, inv: Inventario, tipo: str, cantidad: int):
    ctx.db.add(MovimientoInventario(variante_id=inv.variante_id, sucursal_id=inv.sucursal_id, tipo=tipo,
                                    cantidad=cantidad, stock_disponible_resultante=inv.stock_disponible or 0,
                                    referencia=sol.codigo, usuario_id=ctx.usuario.id, fecha=_ahora()))


def _ingresar_devueltas(ctx: Contexto, sol: SolicitudDevolucion):
    """La prenda devuelta suma al stock vendible solo si es apta; si no, queda como no disponible."""
    if sol.inventario_ingresado:
        return
    for d in sol.detalles:
        inv = _inventario(ctx, sol.sucursal_id, d.variante_id)
        if sol.inspeccion in APTAS:
            inv.stock_disponible = (inv.stock_disponible or 0) + d.cantidad
            _movimiento(ctx, sol, inv, "INGRESO_DEVOLUCION", d.cantidad)
        else:
            inv.stock_no_disponible = (inv.stock_no_disponible or 0) + d.cantidad
            _movimiento(ctx, sol, inv, "INGRESO_NO_APTO", d.cantidad)
    sol.inventario_ingresado = True


def _verificar_stock(ctx: Contexto, sucursal_id: int, pedidos: dict) -> dict:
    """Bloquea y verifica el stock de las variantes a entregar. Si falta, 409 con la disponibilidad (CU-08)."""
    inventarios, faltan = {}, []
    for variante_id in sorted(pedidos):
        inv = _inventario(ctx, sucursal_id, variante_id)
        if (inv.stock_disponible or 0) < pedidos[variante_id]:
            faltan.append(variante_id)
        inventarios[variante_id] = inv
    if faltan:
        ctx.db.rollback()
        raise HTTPException(status_code=409, detail=f"Sin stock en la sucursal para las variantes {faltan}. Consulte "
                                                    "la disponibilidad en otras sucursales o use la opción sin stock.")
    return inventarios


def disponibilidad(ctx: Contexto, variante_id: int) -> dict:
    v = ctx.db.get(VariantePrenda, variante_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Variante no encontrada")
    filas = (ctx.db.query(Sucursal.id, Sucursal.nombre, VariantePrenda.id, VariantePrenda.talla, VariantePrenda.color,
                          Inventario.stock_disponible)
             .join(Inventario, Inventario.sucursal_id == Sucursal.id)
             .join(VariantePrenda, Inventario.variante_id == VariantePrenda.id)
             .filter(Sucursal.empresa_id == ctx.empresa_id, Sucursal.activa.is_(True),
                     VariantePrenda.prenda_id == v.prenda_id).all())
    return {"prenda_id": v.prenda_id, "variante_id": v.id,
            "en_sucursales": [{"sucursal_id": s, "sucursal": n, "variante_id": vid, "talla": t, "color": c,
                               "stock": int(st or 0)} for s, n, vid, t, c, st in filas if (st or 0) > 0]}


# ---------------------------------------------------------------- notas de crédito (CU-07)
def _estado_nota(n: NotaCredito) -> str:
    if n.saldo <= 0.009:
        return "USADA"
    return "VENCIDA" if n.vence_en < _ahora() else "VIGENTE"


def vista_nota(n: NotaCredito) -> dict:
    return {"codigo": n.codigo, "cliente": {"id": n.cliente.id, "nombre": n.cliente.nombre_completo} if n.cliente else None,
            "monto": _dinero(n.monto_inicial), "saldo": _dinero(n.saldo), "emitida_en": _iso(n.emitida_en),
            "vence_en": _iso(n.vence_en), "estado": _estado_nota(n),
            "movimientos": [{"tipo": m.tipo, "monto": _dinero(m.monto), "orden_id": m.orden_id, "fecha": _iso(m.fecha)}
                            for m in n.movimientos]}


def _emitir_nota(ctx: Contexto, sol: SolicitudDevolucion, monto: float) -> NotaCredito:
    politica = politica_vigente(ctx)
    nota = NotaCredito(cliente_id=sol.cliente_id, sucursal_id=sol.sucursal_id, monto_inicial=_dinero(monto),
                       saldo=_dinero(monto), emitida_en=_ahora(), emitida_por=ctx.usuario.id,
                       vence_en=_ahora() + timedelta(days=politica.vigencia_nota_credito_dias))
    ctx.db.add(nota)
    ctx.db.flush()
    nota.codigo = f"NC-{nota.id:06d}"
    nota.movimientos.append(MovimientoNotaCredito(tipo="EMISION", monto=_dinero(monto), solicitud_id=sol.id,
                                                  usuario_id=ctx.usuario.id, fecha=_ahora()))
    sol.nota_credito_id = nota.id
    sol.nota_credito = nota
    return nota


def listar_notas(ctx: Contexto) -> list[dict]:
    q = ctx.db.query(NotaCredito).filter(NotaCredito.empresa_id == ctx.empresa_id)
    if ctx.rol == ROL_CLIENTE:
        q = q.filter(NotaCredito.cliente_id == ctx.usuario.id)
    return [vista_nota(n) for n in q.order_by(NotaCredito.emitida_en.desc()).limit(200)]


def consultar_nota(ctx: Contexto, codigo: str) -> dict:
    n = ctx.db.query(NotaCredito).filter(NotaCredito.codigo == codigo).first()
    if n is None or (ctx.rol == ROL_CLIENTE and n.cliente_id != ctx.usuario.id):
        raise HTTPException(status_code=404, detail="Nota de crédito no encontrada")
    return vista_nota(n)


def aplicar_nota(ctx: Contexto, codigo: str, orden: Orden, monto_maximo: float) -> float:
    """Usa el saldo de una nota como pago de una venta (pago mixto si no alcanza). Devuelve el monto aplicado."""
    n = ctx.db.query(NotaCredito).filter(NotaCredito.codigo == codigo).with_for_update().first()
    if n is None:
        raise HTTPException(status_code=404, detail="Nota de crédito no encontrada")
    estado = _estado_nota(n)
    if estado != "VIGENTE":
        raise HTTPException(status_code=409, detail=f"La nota de crédito está {estado.lower()}")
    if n.cliente_id and orden.cliente_id and n.cliente_id != orden.cliente_id:
        raise HTTPException(status_code=409, detail="La nota de crédito pertenece a otro cliente")
    aplicado = _dinero(min(n.saldo, monto_maximo))
    n.saldo = _dinero(n.saldo - aplicado)
    n.movimientos.append(MovimientoNotaCredito(tipo="APLICACION", monto=aplicado, orden_id=orden.id,
                                               usuario_id=ctx.usuario.id, fecha=_ahora()))
    return aplicado


# ---------------------------------------------------------------- resoluciones (CU-04, 05, 06, 08)
def _para_resolver(ctx: Contexto, codigo: str) -> SolicitudDevolucion:
    if ctx.rol not in ROLES_PERSONAL:
        raise HTTPException(status_code=403, detail="No tiene permisos para esta operación")
    sol = cargar(ctx, codigo, bloquear=True)
    if sol.estado not in (INSPECCIONADA, PENDIENTE_STOCK):
        raise HTTPException(status_code=409, detail=f"La solicitud debe estar inspeccionada (estado {sol.estado})")
    return sol


def _cerrar(ctx: Contexto, sol: SolicitudDevolucion, estado: str, resolucion: str, accion: str) -> dict:
    sol.estado, sol.resolucion, sol.cerrado_en, sol.cerrado_por = estado, resolucion, _ahora(), ctx.usuario.id
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, accion, "solicitudes_devolucion", sol.id, f"{sol.codigo}: {resolucion}")
    return vista(ctx, sol)


def cambio_variante(ctx: Contexto, codigo: str, body) -> dict:
    sol = _para_resolver(ctx, codigo)
    detalles = {d.id: d for d in sol.detalles}
    pedidos, destinos = {}, []
    for item in body.items:
        d = detalles.get(item.detalle_id)
        if d is None:
            raise HTTPException(status_code=404, detail="La prenda no pertenece a esta solicitud")
        destino = ctx.db.get(VariantePrenda, item.variante_id)
        if destino is None or destino.prenda_id != d.prenda_id:
            raise HTTPException(status_code=422, detail="La variante destino debe ser del mismo modelo")
        if destino.id == d.variante_id:
            raise HTTPException(status_code=422, detail="La variante destino es la misma que se devuelve")
        pedidos[destino.id] = pedidos.get(destino.id, 0) + d.cantidad
        destinos.append((d, destino))
    if sol.recargo > 0 and not body.forma_cobro:
        raise HTTPException(status_code=422, detail=f"Hay un recargo por demora de Bs {sol.recargo}: indique la forma de cobro")

    inventarios = _verificar_stock(ctx, sol.sucursal_id, pedidos)
    _ingresar_devueltas(ctx, sol)
    for variante_id, cantidad in pedidos.items():
        inventarios[variante_id].stock_disponible -= cantidad
        _movimiento(ctx, sol, inventarios[variante_id], "SALIDA_CAMBIO", -cantidad)
    entregas = []
    for d, destino in destinos:
        d.variante_entregada_id, d.cantidad_entregada, d.precio_entregado = destino.id, d.cantidad, d.precio_unitario
        entregas.append({"variante_id": destino.id, "talla": destino.talla, "color": destino.color,
                         "cantidad": d.cantidad, "precio_unitario": _dinero(d.precio_unitario)})
    sol.entregas = entregas
    sol.monto_cobrado, sol.forma_cobro = _dinero(sol.recargo), body.forma_cobro if sol.recargo > 0 else None
    return _cerrar(ctx, sol, CAMBIO_REALIZADO, "CAMBIO_VARIANTE", "CAMBIO")


def cambio_producto(ctx: Contexto, codigo: str, body) -> dict:
    sol = _para_resolver(ctx, codigo)
    pedidos, entregas, nuevo = {}, [], 0.0
    for item in body.items:
        v = ctx.db.get(VariantePrenda, item.variante_id)
        if v is None:
            raise HTTPException(status_code=404, detail="Producto no encontrado")   # de otra empresa: oculto
        precio = _dinero(v.prenda.precio_base)
        pedidos[v.id] = pedidos.get(v.id, 0) + item.cantidad
        entregas.append({"variante_id": v.id, "prenda": v.prenda.nombre, "talla": v.talla, "color": v.color,
                         "cantidad": item.cantidad, "precio_unitario": precio})
        nuevo += item.cantidad * precio
    a_favor = sol.valor_devuelto - sol.recargo
    diferencia = _dinero(nuevo - a_favor)
    if diferencia > 0 and not body.forma_cobro:
        raise HTTPException(status_code=422, detail=f"El producto nuevo cuesta Bs {diferencia} más: indique la forma de cobro")

    inventarios = _verificar_stock(ctx, sol.sucursal_id, pedidos)
    _ingresar_devueltas(ctx, sol)
    for variante_id, cantidad in pedidos.items():
        inventarios[variante_id].stock_disponible -= cantidad
        _movimiento(ctx, sol, inventarios[variante_id], "SALIDA_CAMBIO", -cantidad)
    sol.entregas = entregas
    if diferencia > 0:
        sol.monto_cobrado, sol.forma_cobro = diferencia, body.forma_cobro
    elif diferencia < 0:
        _emitir_nota(ctx, sol, -diferencia)   # saldo a favor del cliente
    return _cerrar(ctx, sol, CAMBIO_REALIZADO, "CAMBIO_PRODUCTO", "CAMBIO")


def reembolso(ctx: Contexto, codigo: str, forma: str) -> dict:
    sol = _para_resolver(ctx, codigo)
    monto = _dinero(sol.valor_devuelto - sol.recargo)
    if forma == "MEDIO_ORIGINAL" and (sol.orden.metodo_pago or "EFECTIVO") not in PAGOS_ELECTRONICOS:
        forma = "EFECTIVO"   # la venta se pagó en efectivo: se devuelve en efectivo
    _ingresar_devueltas(ctx, sol)
    sol.forma_reembolso = forma
    if forma == "NOTA_CREDITO":
        _emitir_nota(ctx, sol, monto)
    else:
        sol.monto_reembolsado = monto
        # Pago electrónico: queda la orden de reembolso para el procesador de pagos
        sol.reembolso_pendiente_procesador = forma == "MEDIO_ORIGINAL"
    return _cerrar(ctx, sol, REEMBOLSADA, "REEMBOLSO", "REEMBOLSO")


def sin_stock(ctx: Contexto, codigo: str, decision: str) -> dict:
    sol = _para_resolver(ctx, codigo)
    _ingresar_devueltas(ctx, sol)   # la prenda ya está en la tienda
    if decision == "NOTA_CREDITO":
        _emitir_nota(ctx, sol, sol.valor_devuelto - sol.recargo)
        return _cerrar(ctx, sol, CERRADA_CON_NOTA, "NOTA_CREDITO", "NOTA_CREDITO")
    if sol.estado == PENDIENTE_STOCK:
        raise HTTPException(status_code=409, detail="La solicitud ya está esperando stock")
    sol.estado = PENDIENTE_STOCK
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "PENDIENTE_STOCK", "solicitudes_devolucion", sol.id, sol.codigo)
    return vista(ctx, sol)
