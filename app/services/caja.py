"""
Apertura y cierre de caja (CU-20).

- Una sola caja abierta por sucursal.
- Durante el turno se acumulan, en efectivo: ventas presenciales y offline ya sincronizadas (menos lo
  pagado con nota de crédito), cobros de diferencias en cambios y reembolsos de devoluciones.
- Al cerrar se ingresa el efectivo contado: si hay diferencia se exige observación y, si supera el umbral
  de la política, la autorización del Encargado o Administrador.
- Las operaciones que el dispositivo todavía tiene en LOCAL se informan como pendientes: se concilian al
  sincronizar porque la venta offline guarda la hora real en que ocurrió.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func

from app.core.contexto import ROLES_GESTION, Contexto
from app.core.security import registrar_bitacora
from app.models.inventario import Orden, Sucursal
from app.models.posventa import (
    CAJA_ABIERTA, CAJA_CERRADA, CAJA_PENDIENTE, MovimientoNotaCredito, SolicitudDevolucion, TurnoCaja,
)
from app.models.usuarios import ROL_ADMIN_EMPRESA, Usuario
from app.services.devoluciones import politica_vigente
from app.services.reportes.consultas import VENTAS_VALIDAS


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _d(v) -> float:
    return round(float(v or 0), 2)


def _sucursal(ctx: Contexto, sucursal_id: Optional[int]) -> Sucursal:
    sid = sucursal_id if ctx.rol == ROL_ADMIN_EMPRESA else ctx.usuario.sucursal_id
    if not sid:
        raise HTTPException(status_code=422, detail="Indique la sucursal de la caja" if ctx.rol == ROL_ADMIN_EMPRESA
                            else "Su usuario no tiene una sucursal asignada")
    s = ctx.db.get(Sucursal, sid)
    if s is None or not s.activa:
        raise HTTPException(status_code=404, detail="Sucursal no encontrada o inactiva")
    return s


def _abierta(ctx: Contexto, sucursal_id: int, bloquear=False) -> Optional[TurnoCaja]:
    q = ctx.db.query(TurnoCaja).filter(TurnoCaja.empresa_id == ctx.empresa_id, TurnoCaja.sucursal_id == sucursal_id,
                                       TurnoCaja.estado == CAJA_ABIERTA)
    return (q.with_for_update() if bloquear else q).first()


def arqueo(ctx: Contexto, turno: TurnoCaja, hasta: datetime) -> dict:
    db, sid, desde = ctx.db, turno.sucursal_id, turno.abierto_en
    ventas = (db.query(Orden.id, Orden.metodo_pago, Orden.canal, Orden.total)
              .filter(Orden.empresa_id == ctx.empresa_id, Orden.sucursal_id == sid,
                      Orden.canal.in_(("PRESENCIAL", "OFFLINE")), Orden.estado.in_(VENTAS_VALIDAS),
                      Orden.fecha_orden >= desde, Orden.fecha_orden < hasta).all())
    con_nota = dict(db.query(MovimientoNotaCredito.orden_id, func.sum(MovimientoNotaCredito.monto))
                    .filter(MovimientoNotaCredito.tipo == "APLICACION",
                            MovimientoNotaCredito.orden_id.in_([v.id for v in ventas] or [-1]))
                    .group_by(MovimientoNotaCredito.orden_id).all())
    por_metodo, efectivo, offline = {}, 0.0, 0
    for oid, metodo, canal, total in ventas:
        metodo = metodo or "EFECTIVO"
        fila = por_metodo.setdefault(metodo, {"metodo_pago": metodo, "ventas": 0, "total": 0.0})
        fila["ventas"] += 1
        fila["total"] = _d(fila["total"] + (total or 0))
        if metodo == "EFECTIVO":
            efectivo += (total or 0) - (con_nota.get(oid) or 0)
        offline += canal == "OFFLINE"

    cerradas = (db.query(SolicitudDevolucion)
                .filter(SolicitudDevolucion.empresa_id == ctx.empresa_id, SolicitudDevolucion.sucursal_id == sid,
                        SolicitudDevolucion.cerrado_en >= desde, SolicitudDevolucion.cerrado_en < hasta).all())
    reembolsos = sum(s.monto_reembolsado for s in cerradas if s.forma_reembolso == "EFECTIVO")
    cobros = sum(s.monto_cobrado for s in cerradas if s.forma_cobro == "EFECTIVO")
    esperado = turno.fondo_inicial + efectivo + cobros - reembolsos
    return {
        "fondo_inicial": _d(turno.fondo_inicial),
        "ventas": {"cantidad": len(ventas), "offline_sincronizadas": offline,
                   "total": _d(sum(v.total or 0 for v in ventas)), "por_metodo": list(por_metodo.values()),
                   "pagado_con_nota_credito": _d(sum(con_nota.values()))},
        "ventas_efectivo": _d(efectivo),
        "cobros_cambios_efectivo": _d(cobros),
        "reembolsos_efectivo": _d(reembolsos),
        "devoluciones_atendidas": len(cerradas),
        "efectivo_esperado": _d(esperado),
    }


def vista(ctx: Contexto, t: TurnoCaja, con_arqueo_en_vivo: bool = False) -> dict:
    nombres = {u.id: u.nombre_completo for u in ctx.db.query(Usuario).filter(
        Usuario.id.in_({i for i in (t.abierto_por, t.cerrado_por, t.autorizado_por) if i}))}
    datos = {
        "id": t.id, "estado": t.estado, "sucursal": {"id": t.sucursal.id, "nombre": t.sucursal.nombre},
        "abierto_por": nombres.get(t.abierto_por), "abierto_en": t.abierto_en.isoformat() + "Z",
        "fondo_inicial": _d(t.fondo_inicial), "cerrado_por": nombres.get(t.cerrado_por),
        "cerrado_en": t.cerrado_en.isoformat() + "Z" if t.cerrado_en else None,
        "efectivo_contado": t.efectivo_contado, "efectivo_esperado": t.efectivo_esperado, "diferencia": t.diferencia,
        "observacion": t.observacion, "pendientes_locales": t.pendientes_locales,
        "autorizado_por": nombres.get(t.autorizado_por), "arqueo": t.resumen,
    }
    if con_arqueo_en_vivo and t.estado == CAJA_ABIERTA:
        datos["arqueo"] = arqueo(ctx, t, _ahora())
    return datos


def abrir(ctx: Contexto, fondo_inicial: float, sucursal_id: Optional[int]) -> dict:
    s = _sucursal(ctx, sucursal_id)
    actual = _abierta(ctx, s.id, bloquear=True)
    if actual:
        raise HTTPException(status_code=409, detail=f"Ya hay una caja abierta en {s.nombre} desde "
                                                    f"{actual.abierto_en.isoformat()}Z: ciérrela antes de abrir otra.")
    t = TurnoCaja(sucursal_id=s.id, estado=CAJA_ABIERTA, abierto_por=ctx.usuario.id, abierto_en=_ahora(),
                  fondo_inicial=_d(fondo_inicial))
    ctx.db.add(t)
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "ABRIR_CAJA", "turnos_caja", t.id, f"{s.nombre}: fondo Bs {t.fondo_inicial}")
    return vista(ctx, t, con_arqueo_en_vivo=True)


def actual(ctx: Contexto, sucursal_id: Optional[int]) -> dict:
    s = _sucursal(ctx, sucursal_id)
    t = _abierta(ctx, s.id)
    if t is None:
        raise HTTPException(status_code=404, detail=f"No hay una caja abierta en {s.nombre}")
    return vista(ctx, t, con_arqueo_en_vivo=True)


def cerrar(ctx: Contexto, body, sucursal_id: Optional[int]) -> dict:
    s = _sucursal(ctx, sucursal_id)
    t = _abierta(ctx, s.id, bloquear=True)
    if t is None:
        raise HTTPException(status_code=404, detail=f"No hay una caja abierta en {s.nombre}")
    gestion = ctx.rol in ROLES_GESTION
    if t.abierto_por != ctx.usuario.id and not gestion:
        raise HTTPException(status_code=403, detail="Solo quien abrió la caja o el Encargado pueden cerrarla")
    ahora = _ahora()
    resumen = arqueo(ctx, t, ahora)
    diferencia = _d(body.efectivo_contado - resumen["efectivo_esperado"])
    if abs(diferencia) >= 0.01 and not (body.observacion or "").strip():
        raise HTTPException(status_code=422, detail=f"Hay una diferencia de Bs {diferencia}: indique una observación")
    supera = abs(diferencia) > politica_vigente(ctx).umbral_diferencia_caja
    t.estado = CAJA_PENDIENTE if supera and not gestion else CAJA_CERRADA
    if supera and gestion:
        t.autorizado_por, t.autorizado_en = ctx.usuario.id, ahora
    t.cerrado_por, t.cerrado_en = ctx.usuario.id, ahora
    t.efectivo_contado, t.efectivo_esperado, t.diferencia = _d(body.efectivo_contado), resumen["efectivo_esperado"], diferencia
    t.observacion, t.resumen = body.observacion, resumen
    t.pendientes_locales = body.pendientes_locales.model_dump() if body.pendientes_locales else None
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "CERRAR_CAJA", "turnos_caja", t.id,
                       f"{s.nombre}: esperado {resumen['efectivo_esperado']}, contado {t.efectivo_contado}, "
                       f"diferencia {diferencia} ({t.estado})")
    return vista(ctx, t)


def autorizar(ctx: Contexto, turno_id: int) -> dict:
    t = ctx.db.query(TurnoCaja).filter(TurnoCaja.id == turno_id).with_for_update().first()
    propia = None if ctx.rol == ROL_ADMIN_EMPRESA else ctx.usuario.sucursal_id
    if t is None or (propia and t.sucursal_id != propia):
        raise HTTPException(status_code=404, detail="Turno de caja no encontrado")
    if t.estado != CAJA_PENDIENTE:
        raise HTTPException(status_code=409, detail="El turno no tiene una autorización pendiente")
    t.estado, t.autorizado_por, t.autorizado_en = CAJA_CERRADA, ctx.usuario.id, _ahora()
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "AUTORIZAR_CAJA", "turnos_caja", t.id, f"Diferencia {t.diferencia}")
    return vista(ctx, t)


def historial(ctx: Contexto, sucursal_id: Optional[int], limite: int = 50) -> list[dict]:
    q = ctx.db.query(TurnoCaja).filter(TurnoCaja.empresa_id == ctx.empresa_id)
    propia = None if ctx.rol == ROL_ADMIN_EMPRESA else ctx.usuario.sucursal_id
    if propia or sucursal_id:
        q = q.filter(TurnoCaja.sucursal_id == (propia or sucursal_id))
    return [vista(ctx, t) for t in q.order_by(TurnoCaja.abierto_en.desc()).limit(limite)]
