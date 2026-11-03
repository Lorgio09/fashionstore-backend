"""
Operaciones de la propia empresa (tenant): suscripción, límites del plan y sucursales.
CU25 Verificar límites y funcionalidades del plan · RN06 límite de sucursales activas.
"""
from typing import List

from fastapi import APIRouter, Depends, status

from app.core.contexto import ROLES_ADMIN, Contexto, get_contexto, requiere_roles
from app.core.security import registrar_bitacora
from app.models.inventario import Sucursal
from app.schemas.saas import CambioEstadoSucursal, EmpresaResponse, SucursalCreate, SucursalResponse
from app.services import suscripciones as svc
from app.services.validaciones import obtener_o_404

router = APIRouter()


@router.get("/mi-empresa")
def mi_empresa(ctx: Contexto = Depends(get_contexto)):
    """Datos de la empresa del usuario, su plan, uso y funciones habilitadas."""
    return {
        "empresa": EmpresaResponse.model_validate(ctx.empresa),
        "suscripcion": svc.resumen(ctx.db, ctx.empresa_id),
    }


@router.get("/sucursales", response_model=List[SucursalResponse])
def listar_sucursales(ctx: Contexto = Depends(requiere_roles(*ROLES_ADMIN))):
    """Todas las sucursales de la empresa, activas e inactivas (para administración)."""
    return ctx.db.query(Sucursal).order_by(Sucursal.id).all()


@router.post("/sucursales", response_model=SucursalResponse, status_code=status.HTTP_201_CREATED)
def crear_sucursal(datos: SucursalCreate, ctx: Contexto = Depends(requiere_roles(*ROLES_ADMIN))):
    svc.verificar_cupo_sucursales(ctx.db, ctx.empresa_id)
    sucursal = Sucursal(nombre=datos.nombre, direccion=datos.direccion, activa=True)
    ctx.db.add(sucursal)
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "INSERTAR", "sucursales", sucursal.id, f"Sucursal {sucursal.nombre}")
    return sucursal


@router.patch("/sucursales/{sucursal_id}/estado", response_model=SucursalResponse)
def cambiar_estado_sucursal(
    sucursal_id: int, datos: CambioEstadoSucursal, ctx: Contexto = Depends(requiere_roles(*ROLES_ADMIN))
):
    sucursal = obtener_o_404(ctx.db, Sucursal, sucursal_id, "Sucursal")
    if datos.activa and not sucursal.activa:
        svc.verificar_cupo_sucursales(ctx.db, ctx.empresa_id)
    sucursal.activa = datos.activa
    ctx.db.commit()
    estado = "activada" if datos.activa else "desactivada"
    registrar_bitacora(ctx.db, ctx.usuario.id, "MODIFICAR", "sucursales", sucursal.id, f"Sucursal {estado}")
    return sucursal
