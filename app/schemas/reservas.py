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
    prenda_id: Optional[int] = None
    prenda_nombre: Optional[str] = None
    talla: Optional[str] = None
    color: Optional[str] = None
    precio: Optional[float] = None

    class Config:
        from_attributes = True

# --- Cabecera de la Reserva ---
class ReservaBase(BaseModel):
    fecha_visita: datetime
    sucursal_id: int

class ReservaCreate(ReservaBase):
    # Si reserva un Cliente se usa su propio id; si reserva el personal, debe indicarse.
    cliente_id: Optional[int] = None
    detalles: List[DetalleReservaCreate] # lista de prendas

class ReservaResponse(ReservaBase):
    id: int
    fecha_creacion: datetime
    estado: str
    cliente_id: int
    usuario_id: Optional[int] = None
    sucursal_nombre: Optional[str] = None
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