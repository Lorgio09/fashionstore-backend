from pydantic import BaseModel, EmailStr
from typing import Optional

class UsuarioBase(BaseModel):
    nombre_completo: str
    email: EmailStr
    telefono: Optional[str] = None
    rol_id: int
    sucursal_id: Optional[int] = None

# 1. Molde para el Administrador (Crea empleados completos)
class UsuarioCreate(UsuarioBase):
    password: str

# 2. NUEVO: Molde para Clientes (Registro público rápido)
class ClienteCreate(BaseModel):
    nombre_completo: str
    email: EmailStr
    password: str

# Molde de respuesta
class UsuarioResponse(UsuarioBase):
    id: int
    activo: bool

    class Config:
        from_attributes = True