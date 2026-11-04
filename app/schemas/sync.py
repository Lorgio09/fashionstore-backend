"""Esquemas de la sincronización offline (contrato API §6)."""
from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

MAX_OPERACIONES_POR_LOTE = 50


# ---------- Datos de cada tipo de operación (se validan una por una) ----------
class ItemVentaOffline(BaseModel):
    variante_id: int
    cantidad: int
    precio_unitario: float


class DatosVentaOffline(BaseModel):
    metodo_pago: str
    cliente_id: Optional[int] = None
    nombre_cliente: Optional[str] = Field(None, max_length=100)
    total: float
    items: List[ItemVentaOffline] = Field(min_length=1)


class ItemReservaOffline(BaseModel):
    variante_id: int
    cantidad: int


class DatosReservaOffline(BaseModel):
    cliente_id: Optional[int] = None
    fecha_visita: datetime
    items: List[ItemReservaOffline] = Field(min_length=1)


# ---------- Lote ----------
class OperacionOffline(BaseModel):
    uuid: UUID
    tipo: str
    empresa_id: str
    sucursal_id: int
    usuario_id: int
    creado_en: Optional[datetime] = None
    datos: dict[str, Any]


class LoteOperaciones(BaseModel):
    dispositivo_id: Optional[str] = Field(None, max_length=64)
    operaciones: List[OperacionOffline] = Field(max_length=MAX_OPERACIONES_POR_LOTE)


class ResultadoOperacion(BaseModel):
    uuid: str
    # ERROR: falla temporal del servidor; la operación no se guardó y debe reenviarse más tarde.
    estado: Literal["CONFIRMADA", "RECHAZADA", "CONFLICTO", "DESCONOCIDA", "ERROR"]
    servidor_id: Optional[int] = None
    duplicada: bool = False
    mensaje: Optional[str] = None
    detalle: Optional[dict[str, Any]] = None


class RespuestaLote(BaseModel):
    procesadas: int
    resultados: List[ResultadoOperacion]


class ConsultaEstado(BaseModel):
    uuids: List[str] = Field(max_length=200)


class RespuestaEstado(BaseModel):
    resultados: List[ResultadoOperacion]


# ---------- Resolución de conflictos ----------
class ItemAjuste(BaseModel):
    variante_id: int
    cantidad: int = Field(gt=0)


class ResolverConflicto(BaseModel):
    accion: Literal["RECHAZAR", "AJUSTAR"]
    motivo: Optional[str] = Field(None, max_length=200)
    items: Optional[List[ItemAjuste]] = None
