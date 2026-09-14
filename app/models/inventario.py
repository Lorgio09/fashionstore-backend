from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime,Date
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.database import Base 

class Categoria(Base):
    __tablename__ = "categorias"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), nullable=False)
    
    prendas = relationship("Prenda", back_populates="categoria")

class Proveedor(Base):
    __tablename__ = "proveedores"
    id = Column(Integer, primary_key=True, index=True)
    razon_social = Column(String(100), nullable=False)
    
    prendas = relationship("Prenda", back_populates="proveedor")

class Prenda(Base):
    __tablename__ = "prendas"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String(255))
    precio_base = Column(Float, nullable=False)
    
    imagen_url = Column(String(255), nullable=True)
    
    categoria_id = Column(Integer, ForeignKey("categorias.id"))
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"))
    # Aquí puedes agregar temporada_id y coleccion_id siguiendo la misma lógica
    
    categoria = relationship("Categoria", back_populates="prendas")
    proveedor = relationship("Proveedor", back_populates="prendas")
    variantes = relationship("VariantePrenda", back_populates="prenda")

class VariantePrenda(Base):
    __tablename__ = "variantes_prenda"
    id = Column(Integer, primary_key=True, index=True)
    talla = Column(String(10), nullable=False)
    color = Column(String(30), nullable=False)
    codigo_sku = Column(String(50), unique=True, index=True)
    
    prenda_id = Column(Integer, ForeignKey("prendas.id"))
    
    prenda = relationship("Prenda", back_populates="variantes")
    inventarios = relationship("Inventario", back_populates="variante")

class Sucursal(Base):
    __tablename__ = "sucursales"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    direccion = Column(String(200))
    
    inventarios = relationship("Inventario", back_populates="sucursal")

class Inventario(Base):
    __tablename__ = "inventarios"
    id = Column(Integer, primary_key=True, index=True)
    stock_disponible = Column(Integer, default=0)
    stock_reservado = Column(Integer, default=0)
    
    variante_id = Column(Integer, ForeignKey("variantes_prenda.id"))
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"))
    
    variante = relationship("VariantePrenda", back_populates="inventarios")
    sucursal = relationship("Sucursal", back_populates="inventarios")
    
class Temporada(Base):
    __tablename__ = "temporadas"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), nullable=False)  # Ej: "Verano 2026"
    fecha_inicio = Column(Date, nullable=True)
    fecha_fin = Column(Date, nullable=True)
    
class Coleccion(Base):
    __tablename__ = "colecciones"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)     # Ej: "Urbana 2026"
    descripcion = Column(String(255), nullable=True) # Ej: "Prendas casuales de algodón"