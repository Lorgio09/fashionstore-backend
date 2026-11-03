import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.database import Base
from app.db.tenant import TenantMixin


def _uuid() -> str:
    return str(uuid.uuid4())


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class Plan(Base):
    """Plan de suscripción. Los límites son configurables desde el backend (RN05)."""

    __tablename__ = "planes"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(30), unique=True, nullable=False)  # BASICO, PROFESIONAL
    nombre = Column(String(60), nullable=False)
    precio_mensual = Column(Float, nullable=False, default=0)
    max_sucursales = Column(Integer, nullable=False)
    max_usuarios = Column(Integer, nullable=True)  # None = sin límite
    permite_offline = Column(Boolean, nullable=False, default=True)
    permite_reportes_ia = Column(Boolean, nullable=False, default=False)
    activo = Column(Boolean, nullable=False, default=True)


class Empresa(Base):
    """Empresa contratante = tenant (RN01)."""

    __tablename__ = "empresas"

    id = Column(String(36), primary_key=True, default=_uuid)
    razon_social = Column(String(150), nullable=False)
    nit = Column(String(30), unique=True, nullable=False)
    slug = Column(String(60), unique=True, nullable=False, index=True)  # identificador público de la tienda
    correo = Column(String(100))
    telefono = Column(String(30))
    estado = Column(String(20), nullable=False, default="ACTIVA")  # ACTIVA | SUSPENDIDA
    fecha_registro = Column(DateTime(timezone=True), default=_ahora)

    suscripciones = relationship("Suscripcion", back_populates="empresa")


class Suscripcion(TenantMixin, Base):
    """Plan contratado por una empresa en un periodo. Solo una queda ACTIVA a la vez."""

    __tablename__ = "suscripciones"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("planes.id"), nullable=False)
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin = Column(Date, nullable=False)
    # ACTIVA | SUSPENDIDA | FINALIZADA (cerrada por cambio de plan). VENCIDA se calcula con fecha_fin.
    estado = Column(String(20), nullable=False, default="ACTIVA")
    periodicidad = Column(String(20), nullable=False, default="MENSUAL")  # MENSUAL | ANUAL
    creado_en = Column(DateTime(timezone=True), default=_ahora)

    empresa = relationship("Empresa", back_populates="suscripciones")
    plan = relationship("Plan")
