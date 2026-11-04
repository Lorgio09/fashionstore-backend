"""Sincronización de la operación offline de la PWA y la app móvil (contrato API §6)."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.contexto import ROLES_ADMIN, ROLES_GESTION, ROLES_PERSONAL, Contexto, requiere_funcion, requiere_roles
from app.models.usuarios import ROL_CLIENTE
from app.schemas.sync import ConsultaEstado, LoteOperaciones, RespuestaEstado, RespuestaLote, ResolverConflicto, ResultadoOperacion
from app.services import sincronizacion as svc

router = APIRouter()

# Cualquier usuario de la empresa puede trabajar offline si su plan lo permite (RN07).
TODOS_LOS_ROLES = (ROL_CLIENTE, *ROLES_PERSONAL)
contexto_offline = requiere_funcion("offline", roles=TODOS_LOS_ROLES)


@router.get("/catalogo", summary="Preparar dispositivo: datos para operar sin conexión")
def descargar_catalogo(sucursal_id: Optional[int] = None, ctx: Contexto = Depends(contexto_offline)):
    return svc.catalogo_offline(ctx, sucursal_id)


@router.post("/operaciones", response_model=RespuestaLote, summary="Enviar un lote de operaciones offline")
def enviar_operaciones(lote: LoteOperaciones, ctx: Contexto = Depends(contexto_offline)):
    resultados = svc.procesar_lote(ctx, lote.operaciones, lote.dispositivo_id)
    return {"procesadas": len(resultados), "resultados": resultados}


@router.post("/estado", response_model=RespuestaEstado, summary="Consultar el estado de operaciones enviadas")
def consultar_estado(consulta: ConsultaEstado, ctx: Contexto = Depends(contexto_offline)):
    return {"resultados": svc.consultar_estado(ctx, consulta.uuids)}


@router.get("/conflictos", summary="Operaciones en conflicto por falta de stock")
def listar_conflictos(sucursal_id: Optional[int] = None, ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION))):
    return svc.listar_conflictos(ctx, sucursal_id)


@router.post("/conflictos/{uuid}/resolver", response_model=ResultadoOperacion, summary="Resolver un conflicto")
def resolver_conflicto(uuid: str, cuerpo: ResolverConflicto, ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION))):
    return svc.resolver_conflicto(ctx, uuid, cuerpo)


@router.get("/registro", summary="Bitácora de sincronización de la empresa (RNF10)")
def registro(
    estado: Optional[str] = None,
    desde: Optional[datetime] = None,
    limite: int = Query(200, ge=1, le=1000),
    ctx: Contexto = Depends(requiere_roles(*ROLES_ADMIN)),
):
    return svc.registro_sync(ctx, estado, desde, limite)
