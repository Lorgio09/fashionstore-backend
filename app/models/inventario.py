from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Date, Text, Boolean, UniqueConstraint, text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.database import Base
from app.db.tenant import TenantMixin


class Categoria(TenantMixin, Base):
    __tablename__ = "categorias"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), nullable=False)

    prendas = relationship("Prenda", back_populates="categoria")


class Proveedor(TenantMixin, Base):
    __tablename__ = "proveedores"
    id = Column(Integer, primary_key=True, index=True)
    razon_social = Column(String(100), nullable=False)

    prendas = relationship("Prenda", back_populates="proveedor")


class Prenda(TenantMixin, Base):
    __tablename__ = "prendas"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=True)
    precio_base = Column(Float, nullable=False)

    imagen_url = Column(String(255), nullable=True)

    categoria_id = Column(Integer, ForeignKey("categorias.id"))
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"))

    categoria = relationship("Categoria", back_populates="prendas")
    proveedor = relationship("Proveedor", back_populates="prendas")
    variantes = relationship("VariantePrenda", back_populates="prenda")


class VariantePrenda(TenantMixin, Base):
    __tablename__ = "variantes_prenda"
    # El SKU es único dentro de cada empresa, no en toda la plataforma.
    __table_args__ = (UniqueConstraint("empresa_id", "codigo_sku", name="uq_variante_empresa_sku"),)

    id = Column(Integer, primary_key=True, index=True)
    talla = Column(String(10), nullable=False)
    color = Column(String(30), nullable=False)
    codigo_sku = Column(String(50), index=True)

    prenda_id = Column(Integer, ForeignKey("prendas.id"))

    prenda = relationship("Prenda", back_populates="variantes")
    inventarios = relationship("Inventario", back_populates="variante")


class Sucursal(TenantMixin, Base):
    __tablename__ = "sucursales"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    direccion = Column(String(200))
    # Solo las sucursales activas cuentan para el límite del plan (RN06).
    activa = Column(Boolean, nullable=False, default=True, server_default=text("true"))

    inventarios = relationship("Inventario", back_populates="sucursal")


class Inventario(TenantMixin, Base):
    """Stock de una variante en una sucursal (RN10)."""
    __tablename__ = "inventarios"
    id = Column(Integer, primary_key=True, index=True)
    stock_disponible = Column(Integer, default=0)
    stock_reservado = Column(Integer, default=0)

    variante_id = Column(Integer, ForeignKey("variantes_prenda.id"))
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"))

    variante = relationship("VariantePrenda", back_populates="inventarios")
    sucursal = relationship("Sucursal", back_populates="inventarios")


class Temporada(TenantMixin, Base):
    __tablename__ = "temporadas"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), nullable=False)  # Ej: "Verano 2026"
    fecha_inicio = Column(Date, nullable=True)
    fecha_fin = Column(Date, nullable=True)


class Coleccion(TenantMixin, Base):
    __tablename__ = "colecciones"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String(255), nullable=True)


class Orden(TenantMixin, Base):
    """Venta (web, presencial u offline). Cabecera del comprobante."""
    __tablename__ = "ordenes"

    id = Column(Integer, primary_key=True, index=True)
    nombre_cliente = Column(String(100))
    correo_cliente = Column(String(100))
    telefono_cliente = Column(String(20))
    direccion_envio = Column(String(200), nullable=True)

    total = Column(Float)
    fecha_orden = Column(DateTime, default=datetime.utcnow)
    estado = Column(String(50), default="PENDIENTE")

    # Datos exigidos para ventas presenciales y offline (sección 7.2 del examen)
    canal = Column(String(20), nullable=True)          # WEB | PRESENCIAL | OFFLINE
    metodo_pago = Column(String(20), nullable=True)    # EFECTIVO | QR | TARJETA | STRIPE
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)   # responsable
    cliente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)   # cuando corresponda
    # Identificador generado en el dispositivo: evita duplicados al sincronizar (RNF05)
    uuid_operacion = Column(String(36), unique=True, nullable=True)

    detalles = relationship("DetalleOrden", back_populates="orden")
    sucursal = relationship("Sucursal")


class DetalleOrden(Base):
    """Ítem de una venta. Pertenece a la empresa a través de su orden."""
    __tablename__ = "detalles_orden"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"))
    prenda_id = Column(Integer, ForeignKey("prendas.id"))
    variante_id = Column(Integer, ForeignKey("variantes_prenda.id"))

    cantidad = Column(Integer)
    precio_unitario = Column(Float)

    orden = relationship("Orden", back_populates="detalles")
