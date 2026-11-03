from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.database import Base
from app.db.tenant import TenantMixin


class Reserva(TenantMixin, Base):
    __tablename__ = "reservas"
    id = Column(Integer, primary_key=True, index=True)
    fecha_creacion = Column(DateTime, default=datetime.utcnow)
    fecha_visita = Column(DateTime, nullable=False)  # Horario aproximado de atención
    estado = Column(String(30), default="Pendiente")  # Pendiente, Preparada, Completada, Cancelada

    cliente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False)
    # Empleado que registró la reserva (en tienda u offline)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    # Identificador generado en el dispositivo: evita duplicados al sincronizar (RNF05)
    uuid_operacion = Column(String(36), unique=True, nullable=True)

    cliente = relationship("Usuario", back_populates="reservas", foreign_keys=[cliente_id])
    sucursal = relationship("Sucursal")
    detalles = relationship("DetalleReserva", back_populates="reserva", cascade="all, delete-orphan")


class DetalleReserva(Base):
    """Ítem de una reserva. Pertenece a la empresa a través de su reserva."""
    __tablename__ = "detalles_reserva"
    id = Column(Integer, primary_key=True, index=True)
    cantidad = Column(Integer, default=1, nullable=False)

    reserva_id = Column(Integer, ForeignKey("reservas.id"), nullable=False)
    variante_id = Column(Integer, ForeignKey("variantes_prenda.id"), nullable=False)

    reserva = relationship("Reserva", back_populates="detalles")
    variante = relationship("VariantePrenda")
