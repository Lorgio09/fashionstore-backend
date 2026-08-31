from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app.db.database import SessionLocal
from app.models.inventario import Prenda # Asegúrate de que el modelo esté en este archivo
from app.schemas.catalogo import PrendaResponse

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/prendas", response_model=List[PrendaResponse])
def obtener_catalogo(db: Session = Depends(get_db)):
    # Consulta a la base de datos para obtener todas las prendas
    prendas = db.query(Prenda).all()
    return prendas