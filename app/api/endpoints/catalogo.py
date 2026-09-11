from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import os
from uuid import uuid4
import shutil

from app.db.database import SessionLocal
from app.models.inventario import Prenda, Categoria, Proveedor, Sucursal
from app.schemas.catalogo import PrendaResponse, PrendaCreate, CategoriaBase, CategoriaResponse, ProveedorBase, ProveedorResponse

router = APIRouter()
os.makedirs("static/imagenes", exist_ok=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 1. MOLDES PYDANTIC (Schemas locales)
# ==========================================

class SucursalCreate(BaseModel):
    nombre: str
    direccion: Optional[str] = None
    
class ProveedorCreate(BaseModel):
    nombre: str

# ==========================================
# 2. RUTAS ESTÁTICAS (Siempre arriba)
# ==========================================

# --- PRENDAS (Catálogo) ---
@router.get("/", response_model=List[PrendaResponse])
def obtener_catalogo(db: Session = Depends(get_db)):
    return db.query(Prenda).all()

@router.post("/", response_model=PrendaResponse)
def crear_prenda(
    nombre: str = Form(...),
    descripcion: str = Form(None),
    precio_base: float = Form(...),
    categoria_id: int = Form(...),
    proveedor_id: int = Form(...),
    imagen: UploadFile = File(...), 
    db: Session = Depends(get_db)
):
    extension = imagen.filename.split(".")[-1]
    nombre_archivo = f"{uuid4()}.{extension}"
    ruta_guardado = f"static/imagenes/{nombre_archivo}"

    with open(ruta_guardado, "wb") as buffer:
        shutil.copyfileobj(imagen.file, buffer)

    url_imagen_db = f"http://localhost:8000/static/imagenes/{nombre_archivo}"

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

# --- SUCURSALES ---
@router.get("/sucursales")
def obtener_sucursales(db: Session = Depends(get_db)):
    return db.query(Sucursal).all()

@router.post("/sucursales")
def crear_sucursal(sucursal: SucursalCreate, db: Session = Depends(get_db)):
    nueva_sucursal = Sucursal(
        nombre=sucursal.nombre, 
        direccion=sucursal.direccion
    )
    db.add(nueva_sucursal)
    db.commit()
    db.refresh(nueva_sucursal)
    return nueva_sucursal

# --- CATEGORÍAS ---
@router.get("/categorias", response_model=List[CategoriaResponse])
def obtener_categorias(db: Session = Depends(get_db)):
    return db.query(Categoria).all()

@router.post("/categorias", response_model=CategoriaResponse)
def crear_categoria(categoria: CategoriaBase, db: Session = Depends(get_db)):
    nueva_categoria = Categoria(nombre=categoria.nombre)
    db.add(nueva_categoria)
    db.commit()
    db.refresh(nueva_categoria)
    return nueva_categoria

# --- PROVEEDORES ---
@router.get("/proveedores", response_model=List[ProveedorResponse])
def obtener_proveedores(db: Session = Depends(get_db)):
    return db.query(Proveedor).all()

@router.post("/proveedores")
def crear_proveedor(proveedor: ProveedorCreate, db: Session = Depends(get_db)):
    nuevo_proveedor = Proveedor(razon_social=proveedor.nombre)
    db.add(nuevo_proveedor)
    db.commit()
    db.refresh(nuevo_proveedor)
    return nuevo_proveedor


# ==========================================
# 3. RUTAS DINÁMICAS (Siempre al final)
# ==========================================

@router.get("/{prenda_id}", response_model=PrendaResponse)
def obtener_prenda(prenda_id: int, db: Session = Depends(get_db)):
    prenda = db.query(Prenda).filter(Prenda.id == prenda_id).first()
    if not prenda:
        raise HTTPException(status_code=404, detail="Prenda no encontrada")
    return prenda

@router.put("/{prenda_id}", response_model=PrendaResponse)
def actualizar_prenda(
    prenda_id: int,
    nombre: str = Form(None),
    descripcion: str = Form(None),
    precio_base: float = Form(None),
    categoria_id: int = Form(None),
    proveedor_id: int = Form(None),
    imagen: UploadFile = File(None), 
    db: Session = Depends(get_db)
):
    prenda = db.query(Prenda).filter(Prenda.id == prenda_id).first()
    if not prenda:
        raise HTTPException(status_code=404, detail="Prenda no encontrada")

    if nombre: prenda.nombre = nombre
    if descripcion: prenda.descripcion = descripcion
    if precio_base: prenda.precio_base = precio_base
    if categoria_id: prenda.categoria_id = categoria_id
    if proveedor_id: prenda.proveedor_id = proveedor_id

    if imagen:
        extension = imagen.filename.split(".")[-1]
        nombre_archivo = f"{uuid4()}.{extension}"
        ruta_guardado = f"static/imagenes/{nombre_archivo}"
        with open(ruta_guardado, "wb") as buffer:
            shutil.copyfileobj(imagen.file, buffer)
        prenda.imagen_url = f"http://localhost:8000/static/imagenes/{nombre_archivo}"

    db.commit()
    db.refresh(prenda)
    return prenda

@router.delete("/{prenda_id}")
def eliminar_prenda(prenda_id: int, db: Session = Depends(get_db)):
    prenda = db.query(Prenda).filter(Prenda.id == prenda_id).first()
    if not prenda:
        raise HTTPException(status_code=404, detail="Prenda no encontrada")
    
    db.delete(prenda)
    db.commit()
    return {"mensaje": "Prenda eliminada con éxito"}