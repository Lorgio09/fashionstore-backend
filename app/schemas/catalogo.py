from pydantic import BaseModel
from typing import List, Optional

class VarianteCreate(BaseModel):
    talla: str
    color: str
    codigo_sku: str

class PrendaCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    precio_base: float
    categoria_id: int
    proveedor_id: int
    variantes: Optional[List[VarianteCreate]] = []


class VarianteResponse(BaseModel):
    id: int
    talla: str
    color: str
    codigo_sku: str

    class Config:
        from_attributes = True

class PrendaResponse(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str] = None
    precio_base: float
    imagen_url: Optional[str] = None
    variantes: List[VarianteResponse] = [] 

    class Config:
        from_attributes = True
        
# --- ESQUEMAS PARA CATEGORÍA ---
class CategoriaBase(BaseModel):
    nombre: str

class CategoriaResponse(CategoriaBase):
    id: int
    
    class Config:
        from_attributes = True  # Permite leer desde modelos de SQLAlchemy

# --- ESQUEMAS PARA PROVEEDOR ---
class ProveedorBase(BaseModel):
    razon_social: str

class ProveedorResponse(ProveedorBase):
    id: int
    
    class Config:
        from_attributes = True
        
class VarianteStockCreate(BaseModel):
    prenda_id: int
    talla: str
    color: str
    codigo_sku: str
    sucursal_id: int
    cantidad: int  # Cuánto stock entra