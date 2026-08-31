from pydantic import BaseModel
from typing import List, Optional

# Esquema para las variantes (Tallas y colores)
class VarianteResponse(BaseModel):
    id: int
    talla: str
    color: str
    codigo_sku: str

    class Config:
        from_attributes = True

# Esquema principal de la Prenda
class PrendaResponse(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str] = None
    precio_base: float
    variantes: List[VarianteResponse] = [] # Incluye las tallas disponibles

    class Config:
        from_attributes = True