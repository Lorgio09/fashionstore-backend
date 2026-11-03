from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base
from app.db.tenant import TenantMixin

# Nombres de rol usados por la lógica de autorización (la tabla roles es un catálogo global)
ROL_CLIENTE = "Cliente"
ROL_ADMIN_EMPRESA = "Administrador"
ROL_ENCARGADO = "Encargado de sucursal"
ROL_CAJERO = "Cajero"
ROL_ADMIN_PLATAFORMA = "Administrador de plataforma"


class Rol(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), unique=True, nullable=False)
    descripcion = Column(String(150))

    usuarios = relationship("Usuario", back_populates="rol")


class Usuario(TenantMixin, Base):
    __tablename__ = "usuarios"
    # Solo el Administrador de plataforma no pertenece a ninguna empresa.
    __tenant_nullable__ = True

    id = Column(Integer, primary_key=True, index=True)
    nombre_completo = Column(String(150), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    telefono = Column(String(20))
    activo = Column(Boolean, default=True)

    rol_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    # Si el usuario es un Cajero o Encargado, debe estar asignado a una sucursal específica
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=True)

    rol = relationship("Rol", back_populates="usuarios")
    sucursal = relationship("Sucursal")
    reservas = relationship("Reserva", back_populates="cliente", foreign_keys="Reserva.cliente_id")
    empresa = relationship("Empresa")
