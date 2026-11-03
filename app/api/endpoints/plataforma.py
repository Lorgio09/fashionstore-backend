"""
Administración de la plataforma SaaS (actor: Administrador de plataforma).
CU21 Registrar empresa contratante · CU22 Administrar suscripciones · CU23 Configurar planes.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.contexto import ContextoPlataforma, get_contexto_plataforma
from app.core.security import get_password_hash, registrar_bitacora
from app.models.saas import Empresa, Plan, Suscripcion
from app.models.usuarios import ROL_ADMIN_EMPRESA, Rol, Usuario
from app.schemas.saas import (
    AsignarPlan,
    CambioEstadoEmpresa,
    CambioEstadoSuscripcion,
    EmpresaCreate,
    EmpresaResponse,
    PlanBase,
    PlanResponse,
    SuscripcionResponse,
)
from app.services import suscripciones as svc

router = APIRouter()


def _empresa_o_404(ctx: ContextoPlataforma, empresa_id: str) -> Empresa:
    empresa = ctx.db.get(Empresa, empresa_id)
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return empresa


def _plan_por_codigo(ctx: ContextoPlataforma, codigo: str) -> Plan:
    plan = ctx.db.query(Plan).filter(Plan.codigo == codigo.upper()).first()
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan {codigo} no encontrado")
    return plan


# ---------------- PLANES (CU23) ----------------
@router.get("/planes", response_model=List[PlanResponse])
def listar_planes(ctx: ContextoPlataforma = Depends(get_contexto_plataforma)):
    return ctx.db.query(Plan).order_by(Plan.max_sucursales).all()


@router.post("/planes", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def crear_plan(datos: PlanBase, ctx: ContextoPlataforma = Depends(get_contexto_plataforma)):
    datos.codigo = datos.codigo.upper()
    if ctx.db.query(Plan).filter(Plan.codigo == datos.codigo).first():
        raise HTTPException(status_code=409, detail="Ya existe un plan con ese código")
    plan = Plan(**datos.model_dump())
    ctx.db.add(plan)
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "INSERTAR", "planes", plan.id, f"Plan {plan.codigo}")
    return plan


@router.put("/planes/{plan_id}", response_model=PlanResponse)
def actualizar_plan(plan_id: int, datos: PlanBase, ctx: ContextoPlataforma = Depends(get_contexto_plataforma)):
    plan = ctx.db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    datos.codigo = datos.codigo.upper()
    duplicado = ctx.db.query(Plan).filter(Plan.codigo == datos.codigo, Plan.id != plan_id).first()
    if duplicado:
        raise HTTPException(status_code=409, detail="Ya existe un plan con ese código")
    for campo, valor in datos.model_dump().items():
        setattr(plan, campo, valor)
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "MODIFICAR", "planes", plan.id, f"Plan {plan.codigo}")
    return plan


# ---------------- EMPRESAS (CU21) ----------------
@router.get("/empresas")
def listar_empresas(ctx: ContextoPlataforma = Depends(get_contexto_plataforma)):
    empresas = ctx.db.query(Empresa).order_by(Empresa.fecha_registro).all()
    return [
        {**EmpresaResponse.model_validate(e).model_dump(), "suscripcion": svc.resumen(ctx.db, e.id)}
        for e in empresas
    ]


@router.post("/empresas", status_code=status.HTTP_201_CREATED)
def registrar_empresa(datos: EmpresaCreate, ctx: ContextoPlataforma = Depends(get_contexto_plataforma)):
    db = ctx.db
    if db.query(Empresa).filter(Empresa.nit == datos.nit).first():
        raise HTTPException(status_code=409, detail="Ya existe una empresa con ese NIT")
    if db.query(Empresa).filter(Empresa.slug == datos.slug).first():
        raise HTTPException(status_code=409, detail="El identificador (slug) ya está en uso")
    if db.query(Usuario).filter(Usuario.email == datos.admin_email).first():
        raise HTTPException(status_code=409, detail="El correo del administrador ya está registrado")
    plan = _plan_por_codigo(ctx, datos.plan_codigo)
    rol_admin = db.query(Rol).filter(Rol.nombre == ROL_ADMIN_EMPRESA).first()
    if rol_admin is None:
        raise HTTPException(status_code=500, detail=f"No existe el rol '{ROL_ADMIN_EMPRESA}'")

    empresa = Empresa(
        razon_social=datos.razon_social,
        nit=datos.nit,
        slug=datos.slug,
        correo=datos.correo,
        telefono=datos.telefono,
        estado="ACTIVA",
    )
    db.add(empresa)
    db.flush()
    admin = Usuario(
        nombre_completo=datos.admin_nombre,
        email=datos.admin_email,
        password_hash=get_password_hash(datos.admin_password),
        rol_id=rol_admin.id,
        empresa_id=empresa.id,
    )
    db.add(admin)
    svc.asignar_plan(db, empresa.id, plan, datos.periodicidad)
    db.commit()
    registrar_bitacora(db, ctx.usuario.id, "INSERTAR", "empresas", admin.id, f"Empresa {empresa.slug} con plan {plan.codigo}")
    return {
        "empresa": EmpresaResponse.model_validate(empresa),
        "administrador": {"id": admin.id, "email": admin.email},
        "suscripcion": svc.resumen(db, empresa.id),
    }


@router.get("/empresas/{empresa_id}", response_model=EmpresaResponse)
def obtener_empresa(empresa_id: str, ctx: ContextoPlataforma = Depends(get_contexto_plataforma)):
    return _empresa_o_404(ctx, empresa_id)


@router.patch("/empresas/{empresa_id}/estado", response_model=EmpresaResponse)
def cambiar_estado_empresa(
    empresa_id: str, datos: CambioEstadoEmpresa, ctx: ContextoPlataforma = Depends(get_contexto_plataforma)
):
    empresa = _empresa_o_404(ctx, empresa_id)
    empresa.estado = datos.estado
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "MODIFICAR", "empresas", 0, f"Empresa {empresa.slug} -> {datos.estado}")
    return empresa


# ---------------- SUSCRIPCIONES (CU22) ----------------
@router.get("/empresas/{empresa_id}/suscripcion")
def consultar_suscripcion(empresa_id: str, ctx: ContextoPlataforma = Depends(get_contexto_plataforma)):
    _empresa_o_404(ctx, empresa_id)
    return svc.resumen(ctx.db, empresa_id)


@router.get("/empresas/{empresa_id}/suscripciones", response_model=List[SuscripcionResponse])
def historial_suscripciones(empresa_id: str, ctx: ContextoPlataforma = Depends(get_contexto_plataforma)):
    _empresa_o_404(ctx, empresa_id)
    return (
        ctx.db.query(Suscripcion)
        .filter(Suscripcion.empresa_id == empresa_id)
        .order_by(Suscripcion.fecha_inicio.desc(), Suscripcion.id.desc())
        .all()
    )


@router.post("/empresas/{empresa_id}/suscripcion")
def asignar_o_cambiar_plan(
    empresa_id: str, datos: AsignarPlan, ctx: ContextoPlataforma = Depends(get_contexto_plataforma)
):
    empresa = _empresa_o_404(ctx, empresa_id)
    plan = _plan_por_codigo(ctx, datos.plan_codigo)
    svc.asignar_plan(ctx.db, empresa.id, plan, datos.periodicidad, datos.fecha_inicio)
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "MODIFICAR", "suscripciones", 0, f"{empresa.slug} -> plan {plan.codigo}")
    return svc.resumen(ctx.db, empresa.id)


@router.post("/empresas/{empresa_id}/suscripcion/renovar")
def renovar_suscripcion(empresa_id: str, ctx: ContextoPlataforma = Depends(get_contexto_plataforma)):
    empresa = _empresa_o_404(ctx, empresa_id)
    actual = svc.suscripcion_actual(ctx.db, empresa.id)
    if actual is None:
        raise HTTPException(status_code=409, detail="La empresa no tiene una suscripción para renovar")
    svc.renovar(ctx.db, actual)
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "MODIFICAR", "suscripciones", actual.id, f"Renovación {empresa.slug} hasta {actual.fecha_fin}")
    return svc.resumen(ctx.db, empresa.id)


@router.patch("/empresas/{empresa_id}/suscripcion/estado")
def cambiar_estado_suscripcion(
    empresa_id: str, datos: CambioEstadoSuscripcion, ctx: ContextoPlataforma = Depends(get_contexto_plataforma)
):
    empresa = _empresa_o_404(ctx, empresa_id)
    actual = svc.suscripcion_actual(ctx.db, empresa.id)
    if actual is None:
        raise HTTPException(status_code=409, detail="La empresa no tiene suscripción")
    actual.estado = datos.estado
    ctx.db.commit()
    registrar_bitacora(ctx.db, ctx.usuario.id, "MODIFICAR", "suscripciones", actual.id, f"{empresa.slug} -> {datos.estado}")
    return svc.resumen(ctx.db, empresa.id)
