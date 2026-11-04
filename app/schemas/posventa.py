"""Esquemas de posventa (devoluciones y cambios, notas de crédito) y caja."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Motivo = Literal["TALLA", "AJUSTE_MEDIDA", "COLOR", "DEFECTO", "PRODUCTO_EQUIVOCADO", "YA_NO_LO_DESEA"]
Resolucion = Literal["CAMBIO_VARIANTE", "CAMBIO_PRODUCTO", "REEMBOLSO"]
Pago = Literal["EFECTIVO", "QR", "TARJETA"]


class PoliticaIn(BaseModel):
    plazo_cambio_dias: int = Field(ge=1, le=365)
    plazo_garantia_dias: int = Field(ge=1, le=730)
    categorias_no_retornables: List[int] = Field(default_factory=list)
    max_cambios_por_prenda: int = Field(ge=0, le=10)
    max_devoluciones_mes_cliente: int = Field(ge=1, le=50)
    fuera_de_plazo: Literal["RECHAZAR", "RECARGO"] = "RECHAZAR"
    recargo_pct: float = Field(0, ge=0, le=50)
    vigencia_nota_credito_dias: int = Field(180, ge=7, le=730)
    umbral_diferencia_caja: float = Field(50, ge=0)


class ItemSolicitud(BaseModel):
    detalle_orden_id: int
    cantidad: int = Field(gt=0)


class SolicitudIn(BaseModel):
    orden_id: int
    items: List[ItemSolicitud] = Field(min_length=1)
    motivo: Motivo
    resolucion: Resolucion
    sucursal_id: Optional[int] = Field(None, description="Sucursal donde se entrega la prenda (cliente o administrador)")
    observacion: Optional[str] = Field(None, max_length=255)


class InspeccionIn(BaseModel):
    resultado: Literal["APTA", "APTA_CON_DESCUENTO", "NO_APTA", "INCOMPLETA", "RECHAZAR"]
    observacion: Optional[str] = Field(None, max_length=255)


class CambioVarianteItem(BaseModel):
    detalle_id: int = Field(description="id del detalle de la solicitud")
    variante_id: int = Field(description="variante destino del mismo modelo")


class CambioVarianteIn(BaseModel):
    items: List[CambioVarianteItem] = Field(min_length=1)
    forma_cobro: Optional[Pago] = Field(None, description="Solo si hay recargo por demora")


class ProductoDestino(BaseModel):
    variante_id: int
    cantidad: int = Field(gt=0)


class CambioProductoIn(BaseModel):
    items: List[ProductoDestino] = Field(min_length=1)
    forma_cobro: Optional[Pago] = Field(None, description="Obligatoria si el producto nuevo cuesta más")


class ReembolsoIn(BaseModel):
    forma: Literal["EFECTIVO", "MEDIO_ORIGINAL", "NOTA_CREDITO"]


class SinStockIn(BaseModel):
    decision: Literal["NOTA_CREDITO", "ESPERAR_STOCK"]


# ---------------- caja
class AbrirCajaIn(BaseModel):
    fondo_inicial: float = Field(ge=0)
    sucursal_id: Optional[int] = None


class PendientesLocales(BaseModel):
    cantidad: int = Field(0, ge=0)
    monto_efectivo: float = Field(0, ge=0)


class CerrarCajaIn(BaseModel):
    efectivo_contado: float = Field(ge=0)
    observacion: Optional[str] = Field(None, max_length=255)
    pendientes_locales: Optional[PendientesLocales] = None
