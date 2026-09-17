from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

# --- Detalle de la Reserva (Las prendas) ---
class DetalleReservaBase(BaseModel):
    variante_id: int
    cantidad: int

class DetalleReservaCreate(DetalleReservaBase):
    pass

class DetalleReservaResponse(DetalleReservaBase):
    id: int

    class Config:
        from_attributes = True

# --- Cabecera de la Reserva ---
class ReservaBase(BaseModel):
    fecha_visita: datetime
    sucursal_id: int

class ReservaCreate(ReservaBase):
    cliente_id: int
    detalles: List[DetalleReservaCreate] # lista de prendas

class ReservaResponse(ReservaBase):
    id: int
    fecha_creacion: datetime
    estado: str
    cliente_id: int
    detalles: List[DetalleReservaResponse]

    class Config:
        from_attributes = True
        
class ItemCarritoCreate(BaseModel):
    prenda_id: int
    variante_id: int
    cantidad: int
    precio: float

class OrdenCreate(BaseModel):
    nombre_cliente: str
    correo_cliente: str
    telefono_cliente: str
    direccion_envio: Optional[str] = None
    items: List[ItemCarritoCreate]