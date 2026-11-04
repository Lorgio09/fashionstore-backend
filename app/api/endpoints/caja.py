"""Apertura y cierre de caja de la sucursal (CU-20)."""
from typing import Optional

from fastapi import APIRouter, Depends

from app.core.contexto import ROLES_GESTION, ROLES_PERSONAL, Contexto, requiere_roles
from app.schemas.posventa import AbrirCajaIn, CerrarCajaIn
from app.services import caja as svc

router = APIRouter()
personal = requiere_roles(*ROLES_PERSONAL)


@router.post("/abrir", status_code=201, summary="Abrir la caja de la sucursal con el fondo inicial")
def abrir(body: AbrirCajaIn, ctx: Contexto = Depends(personal)):
    return svc.abrir(ctx, body.fondo_inicial, body.sucursal_id)


@router.get("/actual", summary="Caja abierta de la sucursal con el arqueo en vivo")
def actual(sucursal_id: Optional[int] = None, ctx: Contexto = Depends(personal)):
    return svc.actual(ctx, sucursal_id)


@router.post("/cerrar", summary="Cerrar la caja con el efectivo contado (arqueo)")
def cerrar(body: CerrarCajaIn, sucursal_id: Optional[int] = None, ctx: Contexto = Depends(personal)):
    return svc.cerrar(ctx, body, sucursal_id)


@router.post("/{turno_id}/autorizar", summary="Autorizar un cierre con diferencia mayor al umbral")
def autorizar(turno_id: int, ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION))):
    return svc.autorizar(ctx, turno_id)


@router.get("/turnos", summary="Historial de turnos de caja")
def historial(sucursal_id: Optional[int] = None, ctx: Contexto = Depends(personal)):
    return svc.historial(ctx, sucursal_id)
