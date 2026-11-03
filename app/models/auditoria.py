from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.db.database import Base
from app.db.tenant import TenantMixin


class Bitacora(TenantMixin, Base):
    __tablename__ = "bitacora"
    # Las acciones del Administrador de plataforma no pertenecen a una empresa.
    __tenant_nullable__ = True

    id = Column(Integer, primary_key=True, index=True)
    accion = Column(String(50), nullable=False)          # Ej: "INSERTAR", "MODIFICAR", "ELIMINAR"
    tabla_afectada = Column(String(50), nullable=False)  # Ej: "prendas", "usuarios", "sucursales"
    registro_id = Column(Integer, nullable=False)        # El ID del registro afectado
    detalle = Column(String(255), nullable=True)         # Un pequeño resumen de lo que pasó
    fecha_hora = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Vinculamos la acción al empleado responsable
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    usuario = relationship("Usuario")
