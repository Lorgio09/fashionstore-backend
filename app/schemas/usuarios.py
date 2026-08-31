from pydantic import BaseModel, EmailStr
from typing import Optional

# Propiedades compartidas
class UsuarioBase(BaseModel):
    nombre_completo: str
    email: EmailStr
    telefono: Optional[str] = None
    rol_id: int
    sucursal_id: Optional[int] = None

# Datos requeridos para crear un usuario (incluye contraseña)
class UsuarioCreate(UsuarioBase):
    password: str

# Datos que la API devolverá al frontend (ocultando la contraseña)
class UsuarioResponse(UsuarioBase):
    id: int
    activo: bool

    class Config:
        from_attributes = True # Permite que Pydantic lea el modelo de SQLAlchemy