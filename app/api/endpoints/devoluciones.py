"""Devoluciones y cambios (CU-01 a CU-11) y notas de crédito (CU-07)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.contexto import ROLES_ADMIN, ROLES_GESTION, ROLES_PERSONAL, Contexto, get_contexto, requiere_roles
from app.models.usuarios import ROL_CLIENTE
from app.schemas.posventa import (
    CambioProductoIn, CambioVarianteIn, InspeccionIn, PoliticaIn, ReembolsoIn, SinStockIn, SolicitudIn,
)
from app.services import devoluciones as svc

router = APIRouter()
TODOS = (ROL_CLIENTE, *ROLES_PERSONAL)
personal = requiere_roles(*ROLES_PERSONAL)
gestion = requiere_roles(*ROLES_GESTION)
todos = requiere_roles(*TODOS)


# ---------- Política (CU-09)
@router.get("/politica", summary="Política de devoluciones vigente de la empresa")
def ver_politica(ctx: Contexto = Depends(get_contexto)):
    return svc.vista_politica(svc.politica_vigente(ctx))


@router.put("/politica", summary="Configurar la política de devoluciones (Administrador)")
def configurar_politica(body: PoliticaIn, ctx: Contexto = Depends(requiere_roles(*ROLES_ADMIN))):
    return svc.guardar_politica(ctx, body.model_dump())


# ---------- Identificar la venta (CU-01 / CU-02)
@router.get("/ventas", summary="Buscar una venta por comprobante (número de orden) o datos del cliente")
def buscar_ventas(orden_id: Optional[int] = None, cliente: Optional[str] = Query(None, min_length=2),
                  ctx: Contexto = Depends(personal)):
    return svc.buscar_ventas(ctx, orden_id, cliente)


@router.get("/mis-compras", summary="Compras del cliente con las prendas que puede devolver")
def mis_compras(ctx: Contexto = Depends(requiere_roles(ROL_CLIENTE))):
    return svc.mis_compras(ctx)


# ---------- Solicitudes
@router.post("/solicitudes", status_code=201, summary="Registrar una solicitud de devolución o cambio")
def crear(body: SolicitudIn, ctx: Contexto = Depends(todos)):
    return svc.crear_solicitud(ctx, body)


@router.get("/solicitudes", summary="Historial con filtros e indicadores (CU-11)")
def listar(estado: Optional[str] = None, sucursal_id: Optional[int] = None, motivo: Optional[str] = None,
           desde: Optional[date] = None, hasta: Optional[date] = None, ctx: Contexto = Depends(todos)):
    return svc.listar(ctx, estado, sucursal_id, motivo, desde, hasta)


@router.get("/solicitudes/{codigo}", summary="Detalle de una solicitud con las acciones disponibles")
def detalle(codigo: str, ctx: Contexto = Depends(todos)):
    return svc.vista(ctx, svc.cargar(ctx, codigo))


@router.post("/solicitudes/{codigo}/autorizar", summary="Autorizar una solicitud que superó el máximo mensual")
def autorizar(codigo: str, ctx: Contexto = Depends(gestion)):
    return svc.autorizar(ctx, codigo)


@router.post("/solicitudes/{codigo}/inspeccionar", summary="Registrar la inspección de la prenda (CU-03)")
def inspeccionar(codigo: str, body: InspeccionIn, ctx: Contexto = Depends(gestion)):
    return svc.inspeccionar(ctx, codigo, body.resultado, body.observacion)


@router.post("/solicitudes/{codigo}/cambio-variante", summary="Cambio de talla o color del mismo modelo (CU-04)")
def cambio_variante(codigo: str, body: CambioVarianteIn, ctx: Contexto = Depends(personal)):
    return svc.cambio_variante(ctx, codigo, body)


@router.post("/solicitudes/{codigo}/cambio-producto", summary="Cambio por otro producto (CU-05)")
def cambio_producto(codigo: str, body: CambioProductoIn, ctx: Contexto = Depends(personal)):
    return svc.cambio_producto(ctx, codigo, body)


@router.post("/solicitudes/{codigo}/reembolso", summary="Reembolso del dinero (CU-06)")
def reembolso(codigo: str, body: ReembolsoIn, ctx: Contexto = Depends(personal)):
    return svc.reembolso(ctx, codigo, body.forma)


@router.post("/solicitudes/{codigo}/sin-stock", summary="Cambio sin stock: nota de crédito o esperar stock (CU-08)")
def sin_stock(codigo: str, body: SinStockIn, ctx: Contexto = Depends(personal)):
    return svc.sin_stock(ctx, codigo, body.decision)


@router.get("/disponibilidad/{variante_id}", summary="Stock del modelo en todas las sucursales (CU-08)")
def disponibilidad(variante_id: int, ctx: Contexto = Depends(personal)):
    return svc.disponibilidad(ctx, variante_id)


# ---------- Notas de crédito (CU-07)
@router.get("/notas-credito", summary="Notas de crédito (el cliente ve solo las suyas)")
def notas(ctx: Contexto = Depends(todos)):
    return svc.listar_notas(ctx)


@router.get("/notas-credito/{codigo}", summary="Consultar una nota de crédito y su saldo")
def nota(codigo: str, ctx: Contexto = Depends(todos)):
    return svc.consultar_nota(ctx, codigo)
