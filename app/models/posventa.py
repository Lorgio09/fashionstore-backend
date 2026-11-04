"""
Posventa: devoluciones y cambios (CU-01 a CU-11), notas de crédito (CU-07), movimientos de inventario
(CU-10) y apertura/cierre de caja (CU-20). Todo pertenece a una empresa (RN02).
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.database import Base
from app.db.tenant import TenantMixin

# Estados de una solicitud
EN_INSPECCION = "EN_INSPECCION"
INSPECCIONADA = "INSPECCIONADA"
PENDIENTE_STOCK = "PENDIENTE_STOCK"
CAMBIO_REALIZADO = "CAMBIO_REALIZADO"
REEMBOLSADA = "REEMBOLSADA"
CERRADA_CON_NOTA = "CERRADA_CON_NOTA"
RECHAZADA = "RECHAZADA"
ESTADOS_FINALES = (CAMBIO_REALIZADO, REEMBOLSADA, CERRADA_CON_NOTA, RECHAZADA)


class PoliticaDevolucion(TenantMixin, Base):
    """Política de devoluciones de la empresa (CU-09). Se guarda cada versión con su fecha de vigencia."""
    __tablename__ = "politicas_devolucion"

    id = Column(Integer, primary_key=True, index=True)
    plazo_cambio_dias = Column(Integer, nullable=False, default=30)
    plazo_garantia_dias = Column(Integer, nullable=False, default=90)      # defecto de fábrica
    categorias_no_retornables = Column(JSON, nullable=False, default=list)  # ids de categoría
    max_cambios_por_prenda = Column(Integer, nullable=False, default=2)
    max_devoluciones_mes_cliente = Column(Integer, nullable=False, default=3)
    fuera_de_plazo = Column(String(20), nullable=False, default="RECHAZAR")  # RECHAZAR | RECARGO
    recargo_pct = Column(Float, nullable=False, default=0)
    vigencia_nota_credito_dias = Column(Integer, nullable=False, default=180)
    umbral_diferencia_caja = Column(Float, nullable=False, default=50)     # CU-20: más que esto requiere autorización
    vigente_desde = Column(DateTime, nullable=False, default=datetime.utcnow)
    creado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)


class SolicitudDevolucion(TenantMixin, Base):
    __tablename__ = "solicitudes_devolucion"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(20), unique=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False, index=True)
    cliente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False, index=True)  # sucursal receptora
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)                 # quién la registró
    canal = Column(String(20), nullable=False)               # TIENDA | EN_LINEA
    motivo = Column(String(30), nullable=False)
    resolucion_pedida = Column(String(20), nullable=False)   # CAMBIO_VARIANTE | CAMBIO_PRODUCTO | REEMBOLSO
    estado = Column(String(20), nullable=False, default=EN_INSPECCION, index=True)
    creado_en = Column(DateTime, nullable=False, default=datetime.utcnow)

    fuera_de_plazo = Column(Boolean, nullable=False, default=False)
    recargo = Column(Float, nullable=False, default=0)
    requiere_autorizacion = Column(Boolean, nullable=False, default=False)
    autorizado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    inspeccion = Column(String(20), nullable=True)           # APTA | APTA_CON_DESCUENTO | NO_APTA | INCOMPLETA
    inspeccionado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    inspeccionado_en = Column(DateTime, nullable=True)
    observacion = Column(String(255), nullable=True)
    inventario_ingresado = Column(Boolean, nullable=False, default=False)

    resolucion = Column(String(20), nullable=True)           # cómo se cerró
    valor_devuelto = Column(Float, nullable=False, default=0)  # valor pagado de las prendas devueltas
    monto_reembolsado = Column(Float, nullable=False, default=0)
    forma_reembolso = Column(String(20), nullable=True)      # EFECTIVO | MEDIO_ORIGINAL | NOTA_CREDITO
    reembolso_pendiente_procesador = Column(Boolean, nullable=False, default=False)
    monto_cobrado = Column(Float, nullable=False, default=0)  # diferencia pagada por el cliente en un cambio
    entregas = Column(JSON, nullable=True)                    # prendas entregadas en un cambio
    forma_cobro = Column(String(20), nullable=True)
    nota_credito_id = Column(Integer, ForeignKey("notas_credito.id"), nullable=True)
    cerrado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    cerrado_en = Column(DateTime, nullable=True)

    detalles = relationship("DetalleSolicitud", back_populates="solicitud", cascade="all, delete-orphan")
    orden = relationship("Orden")
    sucursal = relationship("Sucursal")
    cliente = relationship("Usuario", foreign_keys=[cliente_id])
    nota_credito = relationship("NotaCredito", foreign_keys=[nota_credito_id])


class DetalleSolicitud(Base):
    """Prenda devuelta (y, si hubo cambio, la que se entregó). Pertenece a la empresa por su solicitud."""
    __tablename__ = "detalles_solicitud"

    id = Column(Integer, primary_key=True, index=True)
    solicitud_id = Column(Integer, ForeignKey("solicitudes_devolucion.id"), nullable=False, index=True)
    detalle_orden_id = Column(Integer, ForeignKey("detalles_orden.id"), nullable=False, index=True)
    prenda_id = Column(Integer, ForeignKey("prendas.id"), nullable=False)
    variante_id = Column(Integer, ForeignKey("variantes_prenda.id"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Float, nullable=False)          # precio efectivamente pagado
    variante_entregada_id = Column(Integer, ForeignKey("variantes_prenda.id"), nullable=True)
    cantidad_entregada = Column(Integer, nullable=True)
    precio_entregado = Column(Float, nullable=True)

    solicitud = relationship("SolicitudDevolucion", back_populates="detalles")


class NotaCredito(TenantMixin, Base):
    """Saldo a favor del cliente para usar en una compra posterior de la misma empresa (CU-07)."""
    __tablename__ = "notas_credito"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(20), unique=True, index=True)
    cliente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)   # nulo: al portador del comprobante
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=True)
    monto_inicial = Column(Float, nullable=False)
    saldo = Column(Float, nullable=False)
    emitida_en = Column(DateTime, nullable=False, default=datetime.utcnow)
    vence_en = Column(DateTime, nullable=False)
    emitida_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    movimientos = relationship("MovimientoNotaCredito", back_populates="nota", cascade="all, delete-orphan")
    cliente = relationship("Usuario", foreign_keys=[cliente_id])


class MovimientoNotaCredito(Base):
    __tablename__ = "movimientos_nota_credito"

    id = Column(Integer, primary_key=True, index=True)
    nota_id = Column(Integer, ForeignKey("notas_credito.id"), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)        # EMISION | APLICACION
    monto = Column(Float, nullable=False)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=True, index=True)
    solicitud_id = Column(Integer, ForeignKey("solicitudes_devolucion.id"), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha = Column(DateTime, nullable=False, default=datetime.utcnow)

    nota = relationship("NotaCredito", back_populates="movimientos")


class MovimientoInventario(TenantMixin, Base):
    """Traza de cada cambio de stock hecho por posventa (CU-10)."""
    __tablename__ = "movimientos_inventario"

    id = Column(Integer, primary_key=True, index=True)
    variante_id = Column(Integer, ForeignKey("variantes_prenda.id"), nullable=False, index=True)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False)        # INGRESO_DEVOLUCION | INGRESO_NO_APTO | SALIDA_CAMBIO
    cantidad = Column(Integer, nullable=False)       # positiva entra, negativa sale
    stock_disponible_resultante = Column(Integer, nullable=False)
    referencia = Column(String(30), nullable=True)   # código de la solicitud
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha = Column(DateTime, nullable=False, default=datetime.utcnow)


# ---------------------------------------------------------------- caja (CU-20)
CAJA_ABIERTA = "ABIERTA"
CAJA_CERRADA = "CERRADA"
CAJA_PENDIENTE = "PENDIENTE_AUTORIZACION"


class TurnoCaja(TenantMixin, Base):
    __tablename__ = "turnos_caja"

    id = Column(Integer, primary_key=True, index=True)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False, index=True)
    estado = Column(String(25), nullable=False, default=CAJA_ABIERTA, index=True)
    abierto_por = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    abierto_en = Column(DateTime, nullable=False, default=datetime.utcnow)
    fondo_inicial = Column(Float, nullable=False)
    cerrado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    cerrado_en = Column(DateTime, nullable=True)
    efectivo_contado = Column(Float, nullable=True)
    efectivo_esperado = Column(Float, nullable=True)
    diferencia = Column(Float, nullable=True)
    observacion = Column(String(255), nullable=True)
    resumen = Column(JSON, nullable=True)            # arqueo al cierre
    pendientes_locales = Column(JSON, nullable=True)  # operaciones aún LOCAL en el dispositivo
    autorizado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    autorizado_en = Column(DateTime, nullable=True)

    sucursal = relationship("Sucursal")
