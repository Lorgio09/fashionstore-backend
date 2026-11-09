"""
CU-19: cambio de prenda registrado sin conexión (operación offline de tipo CAMBIO, contrato §6.5).

El cajero inspecciona la prenda en el momento, entrega la nueva y cobra la diferencia en efectivo; al
sincronizar, el servidor vuelve a validar todo con las mismas reglas del cambio en línea (CU-04/CU-05):
- venta pagada de la empresa, dentro del plazo contado a la fecha real del cambio (la del dispositivo);
- no se devuelve más de lo vendido menos lo ya devuelto; categorías no retornables solo por defecto;
- máximo de cambios por prenda; la diferencia informada debe coincidir con la calculada.
Si algo no se cumple la operación queda RECHAZADA. Si el stock central no alcanza para la prenda
entregada queda en CONFLICTO sin tocar nada; se resuelve desde la web (RECHAZAR o reintentar).

Al confirmarse se crea la solicitud ya cerrada (CAMBIO_REALIZADO, canal OFFLINE) con su traza de
inventario; si la diferencia queda a favor del cliente se emite una nota de crédito.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func

from app.models.inventario import DetalleOrden, Inventario, Orden, Prenda, VariantePrenda
from app.models.posventa import CAMBIO_REALIZADO, RECHAZADA, DetalleSolicitud, SolicitudDevolucion
from app.models.sync import CONFLICTO, OperacionSync
from app.models.usuarios import Usuario
from app.schemas.sync import DatosCambioOffline
from app.services import devoluciones as dev
from app.services.reportes import catalogo
from app.services.reportes.catalogo import OFFSET_HORAS, fmt_fecha
from app.services.reportes.consultas import VENTAS_VALIDAS
from app.services.sincronizacion import TOLERANCIA_TOTAL, Rechazo, SinStock, _cantidades, _variantes

MAX_VENTAS_CATALOGO = 300


def _d(v) -> float:
    return round(float(v or 0), 2)


# ---------------------------------------------------------------- datos para el dispositivo
def politica_offline(ctx) -> dict:
    p = dev.politica_vigente(ctx)
    return {"plazo_cambio_dias": p.plazo_cambio_dias, "plazo_garantia_dias": p.plazo_garantia_dias,
            "categorias_no_retornables": list(p.categorias_no_retornables or []),
            "max_cambios_por_prenda": p.max_cambios_por_prenda, "fuera_de_plazo": p.fuera_de_plazo,
            "recargo_pct": p.recargo_pct}


def ventas_para_cambio(ctx, ids_sucursales: list[int]) -> list[dict]:
    """Ventas recientes de las sucursales, dentro del plazo de cambio, con lo ya devuelto por línea."""
    if not ids_sucursales:
        return []
    db = ctx.db
    politica = dev.politica_vigente(ctx)
    inicio_local = catalogo.hoy_local() - timedelta(days=politica.plazo_cambio_dias)
    desde = datetime.combine(inicio_local, datetime.min.time()) - timedelta(hours=OFFSET_HORAS)
    ordenes = (db.query(Orden)
               .filter(Orden.empresa_id == ctx.empresa_id, Orden.sucursal_id.in_(ids_sucursales),
                       Orden.estado.in_(VENTAS_VALIDAS), Orden.fecha_orden >= desde)
               .order_by(Orden.fecha_orden.desc()).limit(MAX_VENTAS_CATALOGO).all())
    if not ordenes:
        return []
    lineas = (db.query(DetalleOrden, Prenda, VariantePrenda)
              .join(Prenda, DetalleOrden.prenda_id == Prenda.id)
              .join(VariantePrenda, DetalleOrden.variante_id == VariantePrenda.id)
              .filter(DetalleOrden.orden_id.in_([o.id for o in ordenes]))
              .order_by(DetalleOrden.id).all())
    devuelto, cambios = dev._ya_devuelto(ctx, [d.id for d, _, _ in lineas])
    no_retornables = set(politica.categorias_no_retornables or [])
    por_orden = defaultdict(list)
    for d, p, v in lineas:
        por_orden[d.orden_id].append({
            "detalle_orden_id": d.id, "prenda_id": p.id, "prenda": p.nombre, "variante_id": v.id,
            "talla": v.talla, "color": v.color, "cantidad": d.cantidad, "precio_unitario": _d(d.precio_unitario),
            "devuelto": devuelto.get(d.id, 0), "cambios_realizados": cambios.get(d.id, 0),
            "retornable": p.categoria_id not in no_retornables,
        })
    return [{"orden_id": o.id, "uuid_operacion": o.uuid_operacion, "fecha": dev._iso(o.fecha_orden),
             "canal": o.canal, "sucursal_id": o.sucursal_id, "cliente_id": o.cliente_id,
             "nombre_cliente": o.nombre_cliente, "total": _d(o.total), "items": por_orden.get(o.id, [])}
            for o in ordenes]


# ---------------------------------------------------------------- aplicar la operación
def _orden(db, datos: DatosCambioOffline) -> Orden:
    if (datos.orden_id is None) == (datos.venta_uuid is None):
        raise Rechazo("Indique orden_id o venta_uuid de la venta original (solo uno)")
    if datos.orden_id is not None:
        orden = db.get(Orden, datos.orden_id)
    else:
        orden = db.query(Orden).filter(Orden.uuid_operacion == datos.venta_uuid).first()
        if orden is None:
            op = db.query(OperacionSync).filter(OperacionSync.uuid == datos.venta_uuid).first()
            if op is not None and op.estado == CONFLICTO:
                raise Rechazo("La venta original está en conflicto de stock: resuélvala y registre el cambio en línea")
            if op is not None:
                raise Rechazo(f"La venta original no se registró (estado {op.estado})")
    if orden is None:
        raise Rechazo("Venta no encontrada")
    if orden.estado not in VENTAS_VALIDAS:
        raise Rechazo("La venta no está pagada: no admite cambio")
    return orden


def _lineas_devueltas(ctx, orden: Orden, datos: DatosCambioOffline, politica) -> list[tuple[dict, int]]:
    items = dev.vista_venta(ctx, orden, politica)["items"]
    por_id = {i["detalle_orden_id"]: i for i in items}
    pedidas = defaultdict(int)
    elegidas = []
    for d in datos.devueltos:
        if d.cantidad <= 0:
            raise Rechazo("Las cantidades deben ser mayores a cero")
        if d.detalle_orden_id is not None:
            linea = por_id.get(d.detalle_orden_id)
            if linea is not None and d.variante_id is not None and linea["variante_id"] != d.variante_id:
                linea = None
        elif d.variante_id is not None:
            candidatas = [i for i in items if i["variante_id"] == d.variante_id]
            linea = next((i for i in candidatas
                          if i["elegible"] - pedidas[i["detalle_orden_id"]] >= d.cantidad), None) \
                or next(iter(candidatas), None)
        else:
            raise Rechazo("Indique detalle_orden_id o variante_id de cada prenda devuelta")
        if linea is None:
            raise Rechazo("La prenda devuelta no pertenece a la venta",
                          {"detalle_orden_id": d.detalle_orden_id, "variante_id": d.variante_id})
        pedidas[linea["detalle_orden_id"]] += d.cantidad
        if pedidas[linea["detalle_orden_id"]] > linea["elegible"]:
            raise Rechazo(f"{linea['prenda']}: quedan {linea['elegible']} unidad(es) elegibles "
                          f"(vendidas {linea['cantidad']}, ya devueltas {linea['devuelto']})")
        if not linea["retornable"] and datos.motivo != "DEFECTO":
            raise Rechazo(f"{linea['prenda']} pertenece a una categoría no retornable: solo se acepta por defecto de fábrica")
        if linea["cambios_realizados"] >= politica.max_cambios_por_prenda:
            raise Rechazo(f"{linea['prenda']} ya alcanzó el máximo de {politica.max_cambios_por_prenda} cambio(s)")
        elegidas.append((linea, d.cantidad))
    return elegidas


def _verificar_stock(db, sucursal_id: int, pedidos: dict, retorno_apto: dict) -> None:
    """Bloquea las filas de inventario y verifica sin modificar nada. La prenda devuelta apta de la misma
    variante cuenta como disponible (vuelve a la tienda en la misma operación)."""
    faltantes = []
    for variante_id in sorted(set(pedidos) | set(retorno_apto)):
        inv = (db.query(Inventario)
               .filter(Inventario.sucursal_id == sucursal_id, Inventario.variante_id == variante_id)
               .with_for_update().first())
        if variante_id in pedidos:
            disponible = ((inv.stock_disponible or 0) if inv else 0) + retorno_apto.get(variante_id, 0)
            if disponible < pedidos[variante_id]:
                faltantes.append({"variante_id": variante_id, "solicitado": pedidos[variante_id],
                                  "disponible": disponible})
    if faltantes:
        raise SinStock(faltantes)


def aplicar_cambio(ctx, registro, datos: DatosCambioOffline) -> tuple[int, str]:
    db = ctx.db
    usuario = db.get(Usuario, registro.usuario_id)
    # Las funciones de posventa registran como responsable a quien hizo el cambio en el dispositivo
    nctx = SimpleNamespace(db=db, empresa_id=ctx.empresa_id, usuario=usuario, rol=usuario.rol.nombre)
    politica = dev.politica_vigente(nctx)
    momento = registro.creado_en_dispositivo or dev._ahora()

    if datos.inspeccion == "NO_APTA" and datos.motivo != "DEFECTO":
        raise Rechazo("Una prenda no apta solo se cambia si el motivo es defecto de fábrica")
    orden = _orden(db, datos)

    # Plazo contado a la fecha real del cambio (RN: desde la venta original)
    dia_venta, dia_cambio = dev._local(orden.fecha_orden), dev._local(momento)
    if dia_cambio < dia_venta:
        raise Rechazo("La fecha del cambio es anterior a la venta")
    plazo = politica.plazo_garantia_dias if datos.motivo == "DEFECTO" else politica.plazo_cambio_dias
    fuera_de_plazo = (dia_cambio - dia_venta).days > plazo
    if fuera_de_plazo and politica.fuera_de_plazo == "RECHAZAR":
        raise Rechazo(f"Fuera de plazo: el cliente tenía hasta el {fmt_fecha(dia_venta + timedelta(days=plazo))} "
                      f"({plazo} días desde la compra)")

    devueltas = _lineas_devueltas(nctx, orden, datos, politica)
    variantes = _variantes(db, datos.entregados)
    if any(e.precio_unitario < 0 for e in datos.entregados):
        raise Rechazo("Los precios no pueden ser negativos")

    valor_devuelto = _d(sum(linea["precio_unitario"] * c for linea, c in devueltas))
    recargo = _d(valor_devuelto * politica.recargo_pct / 100) if fuera_de_plazo else 0.0
    valor_entregado = _d(sum(e.cantidad * e.precio_unitario for e in datos.entregados))
    diferencia = _d(valor_entregado - (valor_devuelto - recargo))
    importes = {"valor_devuelto": valor_devuelto, "recargo": recargo, "valor_entregado": valor_entregado,
                "diferencia_calculada": diferencia}
    if abs(diferencia - datos.diferencia) > TOLERANCIA_TOTAL:
        raise Rechazo(f"La diferencia informada ({datos.diferencia}) no coincide con la calculada ({diferencia})", importes)
    if diferencia > 0 and datos.forma_cobro != "EFECTIVO":
        raise Rechazo(f"El cliente debe pagar Bs {diferencia}: sin conexión solo se cobra en efectivo (forma_cobro EFECTIVO)")

    pedidos = _cantidades(datos.entregados)
    retorno_apto = defaultdict(int)
    if datos.inspeccion == "APTA":
        for linea, c in devueltas:
            retorno_apto[linea["variante_id"]] += c
    _verificar_stock(db, registro.sucursal_id, pedidos, retorno_apto)

    # ---- desde aquí se modifica la base (todas las validaciones ya pasaron)
    advertencias, excede_maximo = [], False
    if orden.cliente_id:
        recientes = (db.query(func.count(SolicitudDevolucion.id))
                     .filter(SolicitudDevolucion.empresa_id == ctx.empresa_id,
                             SolicitudDevolucion.cliente_id == orden.cliente_id,
                             SolicitudDevolucion.estado != RECHAZADA,
                             SolicitudDevolucion.creado_en >= momento - timedelta(days=30)).scalar())
        excede_maximo = recientes >= politica.max_devoluciones_mes_cliente
        if excede_maximo:
            advertencias.append("El cliente superó el máximo mensual de devoluciones (registrado sin conexión, "
                                "sin autorización previa)")
    if fuera_de_plazo:
        advertencias.append(f"Fuera de plazo: se aplicó un recargo de Bs {recargo}")

    prendas_devueltas = {linea["prenda_id"] for linea, _ in devueltas}
    misma_prenda = all(variantes[e.variante_id].prenda_id in prendas_devueltas for e in datos.entregados)
    resolucion = "CAMBIO_VARIANTE" if misma_prenda else "CAMBIO_PRODUCTO"
    emparejar = len(devueltas) == len(datos.entregados)
    detalles = []
    for i, (linea, c) in enumerate(devueltas):
        det = DetalleSolicitud(detalle_orden_id=linea["detalle_orden_id"], prenda_id=linea["prenda_id"],
                               variante_id=linea["variante_id"], cantidad=c, precio_unitario=linea["precio_unitario"])
        if emparejar:
            e = datos.entregados[i]
            det.variante_entregada_id, det.cantidad_entregada, det.precio_entregado = e.variante_id, e.cantidad, e.precio_unitario
        detalles.append(det)

    sol = SolicitudDevolucion(
        orden_id=orden.id, cliente_id=orden.cliente_id, sucursal_id=registro.sucursal_id, usuario_id=usuario.id,
        canal="OFFLINE", motivo=datos.motivo, resolucion_pedida=resolucion, estado=CAMBIO_REALIZADO,
        creado_en=momento, fuera_de_plazo=fuera_de_plazo, recargo=recargo,
        requiere_autorizacion=excede_maximo,   # queda marcado para revisión: no se pudo pedir autorización
        inspeccion=datos.inspeccion, inspeccionado_por=usuario.id, inspeccionado_en=momento,
        observacion=datos.observacion, valor_devuelto=valor_devuelto, resolucion=resolucion,
        entregas=[{"variante_id": e.variante_id, "prenda": variantes[e.variante_id].prenda.nombre,
                   "talla": variantes[e.variante_id].talla, "color": variantes[e.variante_id].color,
                   "cantidad": e.cantidad, "precio_unitario": _d(e.precio_unitario)} for e in datos.entregados],
        monto_cobrado=diferencia if diferencia > 0 else 0.0, forma_cobro="EFECTIVO" if diferencia > 0 else None,
        cerrado_por=usuario.id, cerrado_en=momento, detalles=detalles,
    )
    db.add(sol)
    db.flush()
    sol.codigo = f"DEV-{sol.id:06d}"

    dev._ingresar_devueltas(nctx, sol)   # apta: vuelve al stock vendible; no apta: no disponible
    for variante_id, cantidad in pedidos.items():
        inv = dev._inventario(nctx, registro.sucursal_id, variante_id)
        inv.stock_disponible = (inv.stock_disponible or 0) - cantidad
        dev._movimiento(nctx, sol, inv, "SALIDA_CAMBIO", -cantidad)
    nota = dev._emitir_nota(nctx, sol, -diferencia) if diferencia < 0 else None

    registro.detalle = {
        "codigo": sol.codigo, "resolucion": resolucion, **importes,
        "monto_cobrado": _d(sol.monto_cobrado),
        "nota_credito": {"codigo": nota.codigo, "monto": _d(nota.monto_inicial), "vence_en": dev._iso(nota.vence_en)}
        if nota else None,
        "advertencias": advertencias,
    }
    return sol.id, f"Cambio registrado ({sol.codigo})"
