from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List
from app.db.database import SessionLocal
from app.models.inventario import Prenda # Asegúrate de que el modelo esté en este archivo
from app.schemas.catalogo import PrendaResponse, PrendaCreate
import os
from uuid import uuid4
import shutil

router = APIRouter()
os.makedirs("static/imagenes", exist_ok=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/", response_model=List[PrendaResponse])
def obtener_catalogo(db: Session = Depends(get_db)):
    # Consulta a la base de datos para obtener todas las prendas
    prendas = db.query(Prenda).all()
    return prendas

# --- NUEVO POST CON SUBIDA DE ARCHIVO ---
@router.post("/", response_model=PrendaResponse)
def crear_prenda(
    nombre: str = Form(...),
    descripcion: str = Form(None),
    precio_base: float = Form(...),
    categoria_id: int = Form(...),
    proveedor_id: int = Form(...),
    imagen: UploadFile = File(...), # Aquí recibimos el archivo físico
    db: Session = Depends(get_db)
):
    # 1. Generar un nombre único para la imagen (para que no se sobreescriban)
    extension = imagen.filename.split(".")[-1]
    nombre_archivo = f"{uuid4()}.{extension}"
    ruta_guardado = f"static/imagenes/{nombre_archivo}"

    # 2. Guardar el archivo físicamente en el servidor
    with open(ruta_guardado, "wb") as buffer:
        shutil.copyfileobj(imagen.file, buffer)

    # 3. La URL que guardaremos en la base de datos (para que Angular la pueda leer luego)
    url_imagen_db = f"http://localhost:8000/static/imagenes/{nombre_archivo}"

    # 4. Guardar en PostgreSQL
    nueva_prenda = Prenda(
        nombre=nombre,
        descripcion=descripcion,
        precio_base=precio_base,
        categoria_id=categoria_id,
        proveedor_id=proveedor_id,
        imagen_url=url_imagen_db
    )
    
    try:
        db.add(nueva_prenda)
        db.commit()
        db.refresh(nueva_prenda)
        return nueva_prenda
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error al guardar: {str(e)}")