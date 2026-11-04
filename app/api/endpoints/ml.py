"""
Módulo de analítica inteligente con Machine Learning (examen 8.4 y 8.5).

Plan Profesional (es parte del Desafío V de IA, igual que los reportes generativos).
El Administrador entrena; Administrador y Encargado consultan. El Encargado solo ve su sucursal.
Cada empresa tiene sus propios modelos, entrenados únicamente con sus datos (RN03).
"""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.contexto import ROLES_ADMIN, Contexto, requiere_funcion
from app.ml import servicio
from app.ml.datos import DatosInsuficientes
from app.models.usuarios import ROL_ENCARGADO

router = APIRouter()
contexto_ml = requiere_funcion("reportes_ia")
contexto_ml_admin = requiere_funcion("reportes_ia", roles=ROLES_ADMIN)


def _alcance(ctx: Contexto, sucursal_id: Optional[int]) -> Optional[list]:
    """El Encargado queda limitado a su sucursal (examen 8.4: alcance del usuario autenticado)."""
    if ctx.rol == ROL_ENCARGADO and ctx.usuario.sucursal_id:
        return [ctx.usuario.sucursal_id]
    return [sucursal_id] if sucursal_id else None


def _sin_datos(e: DatosInsuficientes):
    raise HTTPException(status_code=409, detail=e.mensaje)


@router.post("/entrenar", summary="Entrenar los modelos de demanda y segmentación con los datos de la empresa")
def entrenar(ctx: Contexto = Depends(contexto_ml_admin)):
    try:
        return servicio.entrenar(ctx)
    except DatosInsuficientes as e:
        _sin_datos(e)


@router.get("/modelos", summary="Modelos activos con sus parámetros y métricas de evaluación")
def modelos(ctx: Contexto = Depends(contexto_ml)):
    return servicio.modelos(ctx)


@router.get("/demanda", summary="Predicción de demanda por sucursal y categoría, con cobertura de stock")
def demanda(dias: int = Query(7, ge=1, le=28), sucursal_id: Optional[int] = None,
            categoria_id: Optional[int] = None, ctx: Contexto = Depends(contexto_ml)):
    hoy = servicio._hoy()
    try:
        return servicio.prediccion(ctx, hoy, hoy + timedelta(days=dias - 1), _alcance(ctx, sucursal_id),
                                   [categoria_id] if categoria_id else None)
    except DatosInsuficientes as e:
        _sin_datos(e)


@router.get("/reposicion", summary="Variantes que se agotarían antes de 14 días según la demanda predicha")
def reposicion(sucursal_id: Optional[int] = None, limite: int = Query(10, ge=1, le=100),
               ctx: Contexto = Depends(contexto_ml)):
    try:
        return servicio.alertas_reposicion(ctx, sucursal_ids=_alcance(ctx, sucursal_id), limite=limite)
    except DatosInsuficientes as e:
        _sin_datos(e)


@router.get("/segmentos", summary="Segmentos de clientes (clustering) y la asignación de cada cliente")
def segmentos(ctx: Contexto = Depends(contexto_ml)):
    try:
        return servicio.segmentos(ctx)
    except DatosInsuficientes as e:
        _sin_datos(e)


@router.get("/dashboard", summary="Datos del dashboard analítico: indicadores, serie real + predicción, segmentos y modelos")
def dashboard(sucursal_id: Optional[int] = None, ctx: Contexto = Depends(contexto_ml)):
    return servicio.dashboard(ctx, _alcance(ctx, sucursal_id))
