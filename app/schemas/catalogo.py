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
    # Incluye las tallas/colores disponibles al responder
    variantes: List[VarianteResponse] = [] 

    class Config:
        from_attributes = True