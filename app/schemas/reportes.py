"""Esquemas de los reportes generativos con IA (examen, Desafío V, sección 8)."""
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Agrupacion = Literal["dia", "semana", "mes"]
Canal = Literal["WEB", "PRESENCIAL", "OFFLINE"]
Grafico = Literal["barras", "lineas", "torta", "tabla"]


class Intencion(BaseModel):
    """Qué reporte se pide y con qué filtros. La IA solo produce esto; nunca SQL (8.4)."""
    tipo: str = Field(max_length=40)
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    agrupacion: Optional[Agrupacion] = None
    sucursal_ids: List[int] = Field(default_factory=list, max_length=50)
    categoria_ids: List[int] = Field(default_factory=list, max_length=50)
    prenda_ids: List[int] = Field(default_factory=list, max_length=50)
    canal: Optional[Canal] = None
    limite: Optional[int] = Field(None, ge=1, le=100)
    grafico: Optional[Grafico] = None


class InterpretacionIA(Intencion):
    """Respuesta JSON que se le pide al modelo de IA."""
    tipo: Optional[str] = Field(None, max_length=40)
    estado: Literal["OK", "ACLARACION", "NO_SOPORTADO"]
    mensaje: Optional[str] = Field(None, max_length=500)
    no_reconocidos: List[str] = Field(default_factory=list, max_length=20)


class SolicitudReporte(BaseModel):
    texto: str = Field(min_length=3, max_length=500, description="Pedido escrito o transcrito desde la voz")
    narrativa: bool = Field(True, description="Agregar un resumen redactado por la IA")


class EjecutarReporte(BaseModel):
    intencion: Intencion


class ExportarReporte(BaseModel):
    intencion: Intencion
    formato: Literal["pdf", "xlsx"]
    narrativa: Optional[str] = Field(None, max_length=3000, description="Resumen que se mostró en pantalla")


class VozRequest(BaseModel):
    """Formato del endpoint anterior /ia/generar-reporte (compatibilidad)."""
    texto_voz: str = Field(min_length=3, max_length=500)
