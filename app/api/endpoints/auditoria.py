from typing import List

from fastapi import APIRouter, Depends

from app.core.contexto import ROLES_ADMIN, Contexto, requiere_roles
from app.models.auditoria import Bitacora
from app.schemas.auditoria import BitacoraResponse

router = APIRouter()


@router.get("/", response_model=List[BitacoraResponse])
def obtener_bitacora(ctx: Contexto = Depends(requiere_roles(*ROLES_ADMIN))):
    # Solo la bitácora de la empresa del administrador; el último movimiento primero.
    return ctx.db.query(Bitacora).order_by(Bitacora.fecha_hora.desc()).all()
