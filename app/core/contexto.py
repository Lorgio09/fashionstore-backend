"""
Dependencias de FastAPI que fijan la empresa (tenant) de cada request y verifican permisos.

- ``get_contexto``: usuario autenticado de una empresa. La empresa sale del usuario en la BD,
  nunca de un parámetro de la petición (RN03, RF33).
- ``get_contexto_publico``: tienda pública. Si viene un token válido se usa la empresa del usuario;
  si no, la indicada en el header ``X-Empresa`` (slug) o la empresa pública por defecto.
- ``requiere_roles`` / ``requiere_funcion``: control por rol y por plan (CU25).
- ``get_contexto_plataforma``: Administrador de plataforma, único con acceso global.
"""
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.security import get_usuario_actual, get_usuario_opcional
from app.db.database import get_db
from app.db.tenant import set_global, set_tenant
from app.models.saas import Empresa
from app.models.usuarios import (
    ROL_ADMIN_EMPRESA,
    ROL_ADMIN_PLATAFORMA,
    ROL_CAJERO,
    ROL_ENCARGADO,
    Usuario,
)
from app.services import suscripciones as svc_suscripciones

METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}
EMPRESA_PUBLICA_POR_DEFECTO = os.getenv("EMPRESA_PUBLICA_POR_DEFECTO", "fashionstore")

# Grupos de roles habituales
ROLES_ADMIN = (ROL_ADMIN_EMPRESA,)
ROLES_GESTION = (ROL_ADMIN_EMPRESA, ROL_ENCARGADO)
ROLES_PERSONAL = (ROL_ADMIN_EMPRESA, ROL_ENCARGADO, ROL_CAJERO)


@dataclass
class Contexto:
    db: Session
    usuario: Usuario
    empresa: Empresa

    @property
    def empresa_id(self) -> str:
        return self.empresa.id

    @property
    def rol(self) -> str:
        return self.usuario.rol.nombre


@dataclass
class ContextoPublico:
    db: Session
    empresa: Empresa
    usuario: Optional[Usuario] = None

    @property
    def empresa_id(self) -> str:
        return self.empresa.id


@dataclass
class ContextoPlataforma:
    db: Session
    usuario: Usuario


def _empresa_activa(empresa: Optional[Empresa]) -> Empresa:
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    if empresa.estado != "ACTIVA":
        raise HTTPException(status_code=403, detail="La empresa está suspendida. Contacte al proveedor de la plataforma.")
    return empresa


def get_contexto(
    request: Request,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
) -> Contexto:
    if usuario.empresa_id is None:
        raise HTTPException(status_code=403, detail="Esta operación es exclusiva de usuarios de una empresa")
    empresa = _empresa_activa(db.get(Empresa, usuario.empresa_id))
    set_tenant(db, empresa.id)

    # RN09: con la suscripción vencida o suspendida solo se permite consultar.
    if request.method not in METODOS_LECTURA and not svc_suscripciones.suscripcion_operativa(db, empresa.id):
        raise HTTPException(
            status_code=403,
            detail="La suscripción de la empresa no está vigente: solo se permite consultar información.",
        )
    return Contexto(db=db, usuario=usuario, empresa=empresa)


def get_contexto_publico(
    db: Session = Depends(get_db),
    usuario: Optional[Usuario] = Depends(get_usuario_opcional),
    x_empresa: Optional[str] = Header(None, alias="X-Empresa", description="Slug de la tienda (empresa)"),
) -> ContextoPublico:
    if usuario is not None and usuario.empresa_id is not None:
        empresa = db.get(Empresa, usuario.empresa_id)
    else:
        usuario = None
        slug = (x_empresa or EMPRESA_PUBLICA_POR_DEFECTO).strip().lower()
        empresa = db.query(Empresa).filter(Empresa.slug == slug).first()
    empresa = _empresa_activa(empresa)
    set_tenant(db, empresa.id)
    return ContextoPublico(db=db, empresa=empresa, usuario=usuario)


def requiere_roles(*roles: str):
    def dependencia(ctx: Contexto = Depends(get_contexto)) -> Contexto:
        if ctx.rol not in roles:
            raise HTTPException(status_code=403, detail="No tiene permisos para esta operación")
        return ctx

    return dependencia


def requiere_funcion(funcion: str, roles: tuple = ROLES_GESTION):
    """Verifica rol y que el plan vigente habilite la funcionalidad (RN07)."""

    def dependencia(ctx: Contexto = Depends(requiere_roles(*roles))) -> Contexto:
        svc_suscripciones.verificar_funcion(ctx.db, ctx.empresa_id, funcion)
        return ctx

    return dependencia


def get_contexto_plataforma(
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
) -> ContextoPlataforma:
    if usuario.rol.nombre != ROL_ADMIN_PLATAFORMA:
        raise HTTPException(status_code=403, detail="Solo el Administrador de plataforma puede realizar esta operación")
    set_global(db)
    return ContextoPlataforma(db=db, usuario=usuario)
