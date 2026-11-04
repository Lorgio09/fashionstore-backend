"""
Extracción y preparación de datos para el módulo de ML (examen 8.4, puntos 1 y 2).

Todo se calcula con los datos de UNA empresa (filtro explícito por empresa_id además del filtro
automático del ORM): un modelo nunca aprende de las ventas de otra empresa (RN03).
Las agregaciones se hacen en la base de datos (RNF09).
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.inventario import Categoria, DetalleOrden, Inventario, Orden, Prenda, Sucursal, VariantePrenda
from app.models.usuarios import ROL_CLIENTE, Rol, Usuario
from app.services.reportes.catalogo import OFFSET_HORAS, inicio_utc
from app.services.reportes.consultas import VENTAS_VALIDAS, _a_fecha, _dia_local

DIAS_MAXIMOS_DE_HISTORIA = 365
WEB = None   # las ventas web no tienen sucursal: forman su propia serie ("Tienda en línea")


class DatosInsuficientes(Exception):
    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


@dataclass
class HistoriaDemanda:
    """Unidades vendidas por día para cada serie (sucursal o web, categoría), con ceros en días sin venta."""
    desde: date
    hasta: date
    series: dict = field(default_factory=dict)          # (sucursal_id|None, categoria_id) -> {fecha: unidades}
    sucursales: dict = field(default_factory=dict)      # id|None -> nombre
    categorias: dict = field(default_factory=dict)      # id -> nombre
    ventas: int = 0

    def dias(self) -> list[date]:
        return [self.desde + timedelta(days=i) for i in range((self.hasta - self.desde).days + 1)]


def nombres(db: Session, empresa_id: str) -> tuple[dict, dict]:
    sucursales = {i: n for i, n in db.query(Sucursal.id, Sucursal.nombre).filter(Sucursal.empresa_id == empresa_id)}
    sucursales[WEB] = "Tienda en línea"
    categorias = {i: n for i, n in db.query(Categoria.id, Categoria.nombre).filter(Categoria.empresa_id == empresa_id)}
    return sucursales, categorias


def demanda_diaria(db: Session, empresa_id: str, hasta: date, dias: int = DIAS_MAXIMOS_DE_HISTORIA,
                   desde: Optional[date] = None) -> HistoriaDemanda:
    """Historia de demanda hasta ``hasta`` (inclusive)."""
    desde = desde or hasta - timedelta(days=dias - 1)
    dia = _dia_local(db, Orden.fecha_orden).label("dia")
    filas = (
        db.query(Orden.sucursal_id, Prenda.categoria_id, dia, func.sum(DetalleOrden.cantidad),
                 func.count(func.distinct(Orden.id)))
        .select_from(DetalleOrden)
        .join(Orden, DetalleOrden.orden_id == Orden.id)
        .join(Prenda, DetalleOrden.prenda_id == Prenda.id)
        .filter(Orden.empresa_id == empresa_id, Orden.estado.in_(VENTAS_VALIDAS),
                Orden.fecha_orden >= inicio_utc(desde), Orden.fecha_orden < inicio_utc(hasta + timedelta(days=1)),
                Prenda.categoria_id.isnot(None))
        .group_by(Orden.sucursal_id, Prenda.categoria_id, dia)
        .all()
    )
    sucursales, categorias = nombres(db, empresa_id)
    historia = HistoriaDemanda(desde=desde, hasta=hasta, sucursales=sucursales, categorias=categorias)
    for sucursal_id, categoria_id, d, unidades, _ in filas:
        historia.series.setdefault((sucursal_id, categoria_id), {})[_a_fecha(d)] = int(unidades or 0)
    historia.ventas = (
        db.query(func.count(Orden.id))
        .filter(Orden.empresa_id == empresa_id, Orden.estado.in_(VENTAS_VALIDAS),
                Orden.fecha_orden >= inicio_utc(desde), Orden.fecha_orden < inicio_utc(hasta + timedelta(days=1)))
        .scalar() or 0
    )
    # Preprocesamiento clave: los días sin ventas valen 0 (si no, el modelo solo ve días "buenos").
    for serie in historia.series.values():
        for d in historia.dias():
            serie.setdefault(d, 0)
    return historia


def primera_venta(db: Session, empresa_id: str) -> Optional[date]:
    primera = (db.query(func.min(Orden.fecha_orden))
               .filter(Orden.empresa_id == empresa_id, Orden.estado.in_(VENTAS_VALIDAS)).scalar())
    return primera.date() if primera else None


def stock_por_serie(db: Session, empresa_id: str) -> dict:
    """Stock disponible actual por (sucursal, categoría)."""
    filas = (
        db.query(Inventario.sucursal_id, Prenda.categoria_id, func.sum(Inventario.stock_disponible))
        .join(VariantePrenda, Inventario.variante_id == VariantePrenda.id)
        .join(Prenda, VariantePrenda.prenda_id == Prenda.id)
        .filter(Inventario.empresa_id == empresa_id)
        .group_by(Inventario.sucursal_id, Prenda.categoria_id)
        .all()
    )
    return {(s, c): int(st or 0) for s, c, st in filas}


# ---------------------------------------------------------------- clientes (RFM)


def umbral_premium(db: Session, empresa_id: str) -> float:
    """Precio a partir del cual una prenda se considera cara: percentil 75 del catálogo de la empresa."""
    precios = sorted(p for (p,) in db.query(Prenda.precio_base).filter(Prenda.empresa_id == empresa_id) if p)
    return precios[int(0.75 * (len(precios) - 1))] if precios else 0.0


def variables_clientes(db: Session, empresa_id: str, hoy: date, dias: int = DIAS_MAXIMOS_DE_HISTORIA) -> list[dict]:
    """Una fila por cliente con compras en el período: recencia, frecuencia, monto y hábitos."""
    umbral = umbral_premium(db, empresa_id)
    monto = func.sum(DetalleOrden.cantidad * DetalleOrden.precio_unitario)
    unidades = func.sum(DetalleOrden.cantidad)
    premium = func.sum(case((DetalleOrden.precio_unitario >= umbral, DetalleOrden.cantidad), else_=0))
    web = func.count(func.distinct(case((Orden.canal == "WEB", Orden.id))))
    filas = (
        db.query(Usuario.id, Usuario.nombre_completo, Usuario.email, func.count(func.distinct(Orden.id)),
                 monto, unidades, premium, web, func.max(Orden.fecha_orden))
        .select_from(DetalleOrden)
        .join(Orden, DetalleOrden.orden_id == Orden.id)
        .join(Usuario, Orden.cliente_id == Usuario.id)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(Orden.empresa_id == empresa_id, Usuario.empresa_id == empresa_id, Rol.nombre == ROL_CLIENTE,
                Orden.estado.in_(VENTAS_VALIDAS),
                Orden.fecha_orden >= inicio_utc(hoy - timedelta(days=dias)))
        .group_by(Usuario.id, Usuario.nombre_completo, Usuario.email)
        .all()
    )
    clientes = []
    for cid, nombre, email, compras, total, uds, uds_premium, compras_web, ultima in filas:
        clientes.append({
            "cliente_id": cid, "nombre": nombre, "email": email,
            "recencia_dias": max(0, (hoy - (ultima + timedelta(hours=OFFSET_HORAS)).date()).days),
            "frecuencia": int(compras),
            "monto_total": round(float(total or 0), 2),
            "ticket_promedio": round(float(total or 0) / compras, 2) if compras else 0.0,
            "pct_premium": round(float(uds_premium or 0) / float(uds), 3) if uds else 0.0,
            "pct_web": round(compras_web / compras, 3) if compras else 0.0,
        })
    return clientes
