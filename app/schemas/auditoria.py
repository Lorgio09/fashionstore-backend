from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class BitacoraResponse(BaseModel):
    id: int
    accion: str
    tabla_afectada: str
    registro_id: int
    detalle: Optional[str] = None
    fecha_hora: datetime
    usuario_id: int

    class Config:
        from_attributes = True