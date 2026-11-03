from typing import Iterable, Type

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.inventario import VariantePrenda


def obtener_o_404(db: Session, modelo: Type, id_: int, nombre: str):
    """Busca por id dentro de la empresa actual. Un registro de otra empresa responde
    "no encontrado", sin revelar que existe (CU01 flujo alterno 1)."""
    obj = db.get(modelo, id_)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{nombre} no encontrado(a)")
    return obj


def validar_variantes(db: Session, variante_ids: Iterable[int]) -> None:
    ids = set(variante_ids)
    if not ids:
        raise HTTPException(status_code=422, detail="La operación no tiene ítems")
    encontrados = {v for (v,) in db.query(VariantePrenda.id).filter(VariantePrenda.id.in_(ids)).all()}
    faltan = ids - encontrados
    if faltan:
        raise HTTPException(status_code=404, detail=f"Variantes no encontradas: {sorted(faltan)}")
