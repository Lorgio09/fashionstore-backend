from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.database import Base
from app.db.tenant import TenantMixin

# Estados finales que el servidor asigna a una operación offline
CONFIRMADA = "CONFIRMADA"
RECHAZADA = "RECHAZADA"
CONFLICTO = "CONFLICTO"

TIPO_VENTA = "VENTA"
TIPO_RESERVA = "RESERVA"
TIPO_CAMBIO = "CAMBIO"   # CU-19: cambio de prenda sin conexión


class OperacionSync(TenantMixin, Base):
    """Operación registrada sin conexión (PWA o app móvil) y recibida al sincronizar.

    El ``uuid`` lo genera el dispositivo y es la clave de idempotencia (RNF05): si llega de nuevo,
    se devuelve el resultado guardado. La tabla también es la bitácora de sincronización (RNF10).
    """
    __tablename__ = "operaciones_sync"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(36), unique=True, nullable=False, index=True)
    tipo = Column(String(20), nullable=False)                 # VENTA | RESERVA | CAMBIO
    estado = Column(String(20), nullable=False, index=True)   # CONFIRMADA | RECHAZADA | CONFLICTO

    # Quién la registró en el dispositivo (el usuario del token) y dónde
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=True, index=True)
    dispositivo_id = Column(String(64), nullable=True)

    creado_en_dispositivo = Column(DateTime, nullable=True)
    recibido_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    procesado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    intentos = Column(Integer, default=1, nullable=False)     # veces que el dispositivo la envió

    datos = Column(JSON, nullable=False)                      # operación tal como llegó
    servidor_id = Column(Integer, nullable=True)              # id de la orden o de la reserva creada
    mensaje = Column(String(255), nullable=True)
    detalle = Column(JSON, nullable=True)                     # ítems sin stock, errores de validación

    # Resolución manual de conflictos (Encargado o Administrador)
    resuelto_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    resuelto_en = Column(DateTime, nullable=True)
    resolucion = Column(String(20), nullable=True)            # RECHAZAR | AJUSTAR

    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    resolutor = relationship("Usuario", foreign_keys=[resuelto_por])
    sucursal = relationship("Sucursal")
