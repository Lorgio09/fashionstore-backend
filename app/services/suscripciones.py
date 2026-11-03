"""
Reglas de planes y suscripciones (RN05–RN09, CU22, CU23, CU25).
"""
import calendar
from datetime import date
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.inventario import Sucursal
from app.models.saas import Plan, Suscripcion
from app.models.usuarios import ROL_CLIENTE, Rol, Usuario

FUNCIONES = {
    "reportes_ia": ("permite_reportes_ia", "reportes generativos con IA"),
    "offline": ("permite_offline", "operación sin conexión"),
}
DURACION_MESES = {"MENSUAL": 1, "ANUAL": 12}


def sumar_meses(fecha: date, meses: int) -> date:
    m = fecha.month - 1 + meses
    anio, mes = fecha.year + m // 12, m % 12 + 1
    return date(anio, mes, min(fecha.day, calendar.monthrange(anio, mes)[1]))


def suscripcion_actual(db: Session, empresa_id: str) -> Optional[Suscripcion]:
    """Última suscripción no finalizada de la empresa (puede estar vencida o suspendida)."""
    return (
        db.query(Suscripcion)
        .execution_options(sin_tenant=True)
        .filter(Suscripcion.empresa_id == empresa_id, Suscripcion.estado.in_(["ACTIVA", "SUSPENDIDA"]))
        .order_by(Suscripcion.fecha_inicio.desc(), Suscripcion.id.desc())
        .first()
    )


def estado_efectivo(suscripcion: Optional[Suscripcion], hoy: Optional[date] = None) -> str:
    if suscripcion is None:
        return "SIN_SUSCRIPCION"
    hoy = hoy or date.today()
    if suscripcion.estado == "SUSPENDIDA":
        return "SUSPENDIDA"
    if suscripcion.fecha_fin < hoy:
        return "VENCIDA"
    if suscripcion.fecha_inicio > hoy:
        return "PROGRAMADA"
    return "ACTIVA"


def plan_operativo(db: Session, empresa_id: str) -> Optional[Plan]:
    """Plan que rige hoy, o None si la suscripción no está vigente."""
    s = suscripcion_actual(db, empresa_id)
    return s.plan if estado_efectivo(s) == "ACTIVA" else None


def suscripcion_operativa(db: Session, empresa_id: str) -> bool:
    return plan_operativo(db, empresa_id) is not None


def _plan_o_error(db: Session, empresa_id: str) -> Plan:
    plan = plan_operativo(db, empresa_id)
    if plan is None:
        raise HTTPException(status_code=403, detail="La suscripción de la empresa no está vigente.")
    return plan


def verificar_funcion(db: Session, empresa_id: str, funcion: str) -> None:
    atributo, etiqueta = FUNCIONES[funcion]
    plan = _plan_o_error(db, empresa_id)
    if not getattr(plan, atributo):
        raise HTTPException(
            status_code=403,
            detail=f"El plan {plan.nombre} no incluye {etiqueta}. Actualice al plan Profesional.",
        )


def contar_sucursales_activas(db: Session, empresa_id: str) -> int:
    return (
        db.query(func.count(Sucursal.id))
        .execution_options(sin_tenant=True)
        .filter(Sucursal.empresa_id == empresa_id, Sucursal.activa.is_(True))
        .scalar()
    )


def contar_usuarios_internos(db: Session, empresa_id: str) -> int:
    return (
        db.query(func.count(Usuario.id))
        .execution_options(sin_tenant=True)
        .join(Rol, Usuario.rol_id == Rol.id)
        .filter(Usuario.empresa_id == empresa_id, Usuario.activo.is_(True), Rol.nombre != ROL_CLIENTE)
        .scalar()
    )


def verificar_cupo_sucursales(db: Session, empresa_id: str, adicionales: int = 1) -> None:
    """RN06: no se puede activar una sucursal si la empresa llegó al límite de su plan."""
    plan = _plan_o_error(db, empresa_id)
    activas = contar_sucursales_activas(db, empresa_id)
    if activas + adicionales > plan.max_sucursales:
        raise HTTPException(
            status_code=409,
            detail=(
                f"El plan {plan.nombre} permite hasta {plan.max_sucursales} sucursales activas "
                f"y la empresa ya tiene {activas}."
            ),
        )


def verificar_cupo_usuarios(db: Session, empresa_id: str) -> None:
    plan = _plan_o_error(db, empresa_id)
    if plan.max_usuarios is None:
        return
    actuales = contar_usuarios_internos(db, empresa_id)
    if actuales >= plan.max_usuarios:
        raise HTTPException(
            status_code=409,
            detail=f"El plan {plan.nombre} permite hasta {plan.max_usuarios} usuarios internos.",
        )


def resumen(db: Session, empresa_id: str) -> dict:
    """Plan, estado, fechas, uso y funciones habilitadas (CU25)."""
    s = suscripcion_actual(db, empresa_id)
    estado = estado_efectivo(s)
    plan = s.plan if s else None
    vigente = estado == "ACTIVA"
    return {
        "estado": estado,
        "suscripcion_id": s.id if s else None,
        "plan": {
            "id": plan.id,
            "codigo": plan.codigo,
            "nombre": plan.nombre,
            "max_sucursales": plan.max_sucursales,
            "max_usuarios": plan.max_usuarios,
        } if plan else None,
        "periodicidad": s.periodicidad if s else None,
        "fecha_inicio": s.fecha_inicio if s else None,
        "fecha_fin": s.fecha_fin if s else None,
        "dias_restantes": (s.fecha_fin - date.today()).days if s else None,
        "uso": {
            "sucursales_activas": contar_sucursales_activas(db, empresa_id),
            "usuarios_internos": contar_usuarios_internos(db, empresa_id),
        },
        "funciones": {
            clave: bool(vigente and plan and getattr(plan, atributo))
            for clave, (atributo, _) in FUNCIONES.items()
        },
    }


def asignar_plan(
    db: Session,
    empresa_id: str,
    plan: Plan,
    periodicidad: str = "MENSUAL",
    fecha_inicio: Optional[date] = None,
) -> Suscripcion:
    """Alta o cambio de plan: cierra la suscripción anterior y crea una nueva ACTIVA (CU22)."""
    if periodicidad not in DURACION_MESES:
        raise HTTPException(status_code=422, detail="Periodicidad inválida (MENSUAL o ANUAL)")
    if not plan.activo:
        raise HTTPException(status_code=409, detail="El plan no está disponible")

    activas = contar_sucursales_activas(db, empresa_id)
    if activas > plan.max_sucursales:
        raise HTTPException(
            status_code=409,
            detail=(
                f"La empresa tiene {activas} sucursales activas y el plan {plan.nombre} permite "
                f"{plan.max_sucursales}. Debe desactivar {activas - plan.max_sucursales} antes del cambio."
            ),
        )

    anterior = suscripcion_actual(db, empresa_id)
    if anterior is not None:
        anterior.estado = "FINALIZADA"

    inicio = fecha_inicio or date.today()
    nueva = Suscripcion(
        empresa_id=empresa_id,
        plan_id=plan.id,
        fecha_inicio=inicio,
        fecha_fin=sumar_meses(inicio, DURACION_MESES[periodicidad]),
        periodicidad=periodicidad,
        estado="ACTIVA",
    )
    db.add(nueva)
    db.flush()
    return nueva


def renovar(db: Session, suscripcion: Suscripcion) -> Suscripcion:
    """Renovación administrativa simulada: extiende el periodo desde el vencimiento (o desde hoy si ya venció)."""
    base = max(suscripcion.fecha_fin, date.today())
    suscripcion.fecha_fin = sumar_meses(base, DURACION_MESES.get(suscripcion.periodicidad, 1))
    if suscripcion.estado != "SUSPENDIDA":
        suscripcion.estado = "ACTIVA"
    db.flush()
    return suscripcion
