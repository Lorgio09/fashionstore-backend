from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.db.database import SessionLocal
from app.models.auditoria import Bitacora # Ajusta si lo guardaste en otro lado
from app.schemas.auditoria import BitacoraResponse
from app.core.security import get_usuario_actual
from app.models.usuarios import Usuario # Ajusta la ruta a tu modelo

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/", response_model=List[BitacoraResponse])
def obtener_bitacora(
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual) # ¡Protegemos la ruta!
):
    # .desc() ordena para que el último movimiento salga de primero en la tabla
    return db.query(Bitacora).order_by(Bitacora.fecha_hora.desc()).all()