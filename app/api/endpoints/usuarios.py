from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.contexto import (
    ROLES_ADMIN,
    Contexto,
    ContextoPublico,
    get_contexto_publico,
    requiere_roles,
)
from app.core.security import create_access_token, get_password_hash, get_usuario_actual, registrar_bitacora, verify_password
from app.db.database import get_db
from app.models.inventario import Sucursal
from app.models.saas import Empresa
from app.models.usuarios import ROL_ADMIN_PLATAFORMA, ROL_CLIENTE, Rol, Usuario
from app.schemas.usuarios import ClienteCreate, UsuarioCreate, UsuarioResponse
from app.services import suscripciones as svc_suscripciones
from app.services.validaciones import obtener_o_404

router = APIRouter()


class UsuarioLogin(BaseModel):
    email: EmailStr
    password: str


def _email_registrado(db: Session, email: str) -> bool:
    # El correo es único en toda la plataforma: se busca sin filtro de empresa.
    return (
        db.query(Usuario.id).execution_options(sin_tenant=True).filter(Usuario.email == email).first()
        is not None
    )


def _empresa_publica(empresa: Empresa | None):
    if empresa is None:
        return None
    return {"id": empresa.id, "razon_social": empresa.razon_social, "slug": empresa.slug}


# ==========================================
# 1. REGISTRO PÚBLICO (Para Clientes de una tienda)
# ==========================================
@router.post("/registro/cliente", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def registrar_cliente(cliente: ClienteCreate, ctx: ContextoPublico = Depends(get_contexto_publico)):
    db = ctx.db
    if _email_registrado(db, cliente.email):
        raise HTTPException(status_code=409, detail="El correo ya está registrado")

    rol_cliente = db.query(Rol).filter(Rol.nombre == ROL_CLIENTE).first()
    if not rol_cliente:
        raise HTTPException(status_code=500, detail="Error interno: El rol 'Cliente' no existe en la base de datos")

    # La empresa la asigna el contexto (tienda en la que se registra)
    nuevo_usuario = Usuario(
        nombre_completo=cliente.nombre_completo,
        email=cliente.email,
        password_hash=get_password_hash(cliente.password),
        telefono=None,
        rol_id=rol_cliente.id,
        sucursal_id=None,
    )
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    return nuevo_usuario


# ==========================================
# 2. REGISTRO INTERNO (Administrador de empresa crea empleados) - CU24
# ==========================================
@router.post("/usuarios", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def crear_empleado(usuario: UsuarioCreate, ctx: Contexto = Depends(requiere_roles(*ROLES_ADMIN))):
    db = ctx.db
    if _email_registrado(db, usuario.email):
        raise HTTPException(status_code=409, detail="El correo ya está registrado")

    rol = db.get(Rol, usuario.rol_id)
    if rol is None or rol.nombre == ROL_ADMIN_PLATAFORMA:
        raise HTTPException(status_code=422, detail="Rol inválido")
    if usuario.sucursal_id is not None:
        obtener_o_404(db, Sucursal, usuario.sucursal_id, "Sucursal")
    if rol.nombre != ROL_CLIENTE:
        svc_suscripciones.verificar_cupo_usuarios(db, ctx.empresa_id)

    nuevo_empleado = Usuario(
        nombre_completo=usuario.nombre_completo,
        email=usuario.email,
        password_hash=get_password_hash(usuario.password),
        telefono=usuario.telefono,
        rol_id=usuario.rol_id,
        sucursal_id=usuario.sucursal_id,
    )
    db.add(nuevo_empleado)
    db.commit()
    db.refresh(nuevo_empleado)
    registrar_bitacora(db, ctx.usuario.id, "INSERTAR", "usuarios", nuevo_empleado.id, f"Usuario {nuevo_empleado.email} ({rol.nombre})")
    return nuevo_empleado


@router.post("/login")
def login_usuario(usuario: UsuarioLogin, db: Session = Depends(get_db)):
    db_user = (
        db.query(Usuario).execution_options(sin_tenant=True).filter(Usuario.email == usuario.email).first()
    )
    if not db_user or not verify_password(usuario.password, db_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Correo o contraseña incorrectos")
    if not db_user.activo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="El usuario está desactivado")

    empresa = db.get(Empresa, db_user.empresa_id) if db_user.empresa_id else None
    if empresa is not None and empresa.estado != "ACTIVA":
        raise HTTPException(status_code=403, detail="La empresa está suspendida. Contacte al proveedor de la plataforma.")

    # RF32: la credencial queda asociada al tenant del usuario
    access_token = create_access_token(
        data={
            "sub": db_user.email,
            "id": db_user.id,
            "rol": db_user.rol_id,
            "rol_nombre": db_user.rol.nombre,
            "nombre": db_user.nombre_completo,
            "empresa_id": db_user.empresa_id,
            "sucursal_id": db_user.sucursal_id,
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "usuario": {
            "id": db_user.id,
            "nombre": db_user.nombre_completo,
            "rol_id": db_user.rol_id,
            "rol_nombre": db_user.rol.nombre,
            "sucursal_id": db_user.sucursal_id,
        },
        "empresa": _empresa_publica(empresa),
    }


# ==========================================
# 3. PERFIL
# ==========================================
@router.get("/perfil")
def obtener_perfil(usuario_actual: Usuario = Depends(get_usuario_actual), db: Session = Depends(get_db)):
    empresa = db.get(Empresa, usuario_actual.empresa_id) if usuario_actual.empresa_id else None
    return {
        "mensaje": "¡Acceso autorizado a zona privada!",
        "datos_privados": {
            "nombre": usuario_actual.nombre_completo,
            "email": usuario_actual.email,
            "rol_id": usuario_actual.rol_id,
            "rol_nombre": usuario_actual.rol.nombre,
            "sucursal_id": usuario_actual.sucursal_id,
        },
        "empresa": _empresa_publica(empresa),
    }


@router.get("/roles")
def listar_roles(db: Session = Depends(get_db)):
    # Catálogo global de roles; el de plataforma no se asigna desde una empresa.
    return db.query(Rol).filter(Rol.nombre != ROL_ADMIN_PLATAFORMA).all()


@router.get("/", response_model=List[UsuarioResponse])
def listar_usuarios(ctx: Contexto = Depends(requiere_roles(*ROLES_ADMIN))):
    # Solo usuarios de la empresa y sin exponer password_hash
    return ctx.db.query(Usuario).order_by(Usuario.id).all()
