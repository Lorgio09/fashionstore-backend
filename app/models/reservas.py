from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.database import Base

class Reserva(Base):
    __tablename__ = "reservas"
    id = Column(Integer, primary_key=True, index=True)
    fecha_creacion = Column(DateTime, default=datetime.utcnow)
    fecha_visita = Column(DateTime, nullable=False) # Horario aproximado de atención
    estado = Column(String(30), default="Pendiente") # Pendiente, Preparada, Completada, Cancelada
    
    cliente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False)
    
    cliente = relationship("Usuario", back_populates="reservas")
    sucursal = relationship("Sucursal") 
    detalles = relationship("DetalleReserva", back_populates="reserva", cascade="all, delete-orphan")

class DetalleReserva(Base):
    __tablename__ = "detalles_reserva"
    id = Column(Integer, primary_key=True, index=True)
    cantidad = Column(Integer, default=1, nullable=False)
    
    reserva_id = Column(Integer, ForeignKey("reservas.id"), nullable=False)
    variante_id = Column(Integer, ForeignKey("variantes_prenda.id"), nullable=False)
    
    reserva = relationship("Reserva", back_populates="detalles")
    variante = relationship("VariantePrenda")