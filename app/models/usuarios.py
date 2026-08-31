from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.db.database import Base

class Rol(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), unique=True, nullable=False)
    descripcion = Column(String(150))
    
    usuarios = relationship("Usuario", back_populates="rol")

class Usuario(Base):
    __tablename__ = "usuarios"
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
    reservas = relationship("Reserva", back_populates="cliente")