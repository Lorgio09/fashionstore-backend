from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PlanBase(BaseModel):
    codigo: str = Field(min_length=2, max_length=30)
    nombre: str = Field(min_length=2, max_length=60)
    precio_mensual: float = Field(ge=0, default=0)
    max_sucursales: int = Field(gt=0)
    max_usuarios: Optional[int] = Field(default=None, gt=0)
    permite_offline: bool = True
    permite_reportes_ia: bool = False
    activo: bool = True


class PlanResponse(PlanBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class EmpresaCreate(BaseModel):
    razon_social: str = Field(min_length=2, max_length=150)
    nit: str = Field(min_length=3, max_length=30)
    slug: str = Field(pattern=r"^[a-z0-9-]{3,60}$", description="Identificador público de la tienda")
    correo: Optional[EmailStr] = None
    telefono: Optional[str] = None
    plan_codigo: str = "BASICO"
    periodicidad: Literal["MENSUAL", "ANUAL"] = "MENSUAL"
    # Administrador inicial de la empresa (CU21)
    admin_nombre: str = Field(min_length=2)
    admin_email: EmailStr
    admin_password: str = Field(min_length=6)


class EmpresaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    razon_social: str
    nit: str
    slug: str
    correo: Optional[str] = None
    telefono: Optional[str] = None
    estado: str
    fecha_registro: Optional[datetime] = None


class CambioEstadoEmpresa(BaseModel):
    estado: Literal["ACTIVA", "SUSPENDIDA"]


class AsignarPlan(BaseModel):
    plan_codigo: str
    periodicidad: Literal["MENSUAL", "ANUAL"] = "MENSUAL"
    fecha_inicio: Optional[date] = None


class CambioEstadoSuscripcion(BaseModel):
    estado: Literal["ACTIVA", "SUSPENDIDA"]


class SuscripcionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    empresa_id: str
    fecha_inicio: date
    fecha_fin: date
    estado: str
    periodicidad: str
    plan: PlanResponse


class SucursalCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    direccion: Optional[str] = None


class SucursalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    direccion: Optional[str] = None
    activa: bool


class CambioEstadoSucursal(BaseModel):
    activa: bool
