import os
import shutil
from uuid import uuid4
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db.database import SessionLocal, engine
from app.models.inventario import Prenda, Categoria, Proveedor, Sucursal, Inventario, VariantePrenda, Temporada, Coleccion
from app.models.usuarios import Usuario
from app.schemas.catalogo import PrendaResponse, PrendaCreate, CategoriaBase, CategoriaResponse, ProveedorBase, ProveedorResponse, VarianteStockCreate, TemporadaBase, TemporadaResponse,ColeccionBase,ColeccionResponse
from sqlalchemy import func

# Importaciones de seguridad y auditoría
from app.core.security import get_usuario_actual, registrar_bitacora

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
# 2. RUTAS ESTÁTICAS
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
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual) # ¡Guardia!
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
        
        # AUDITORÍA
        registrar_bitacora(db, usuario_actual.id, "INSERTAR", "prendas", nueva_prenda.id, f"Se creó la prenda: {nueva_prenda.nombre}")
        
        return nueva_prenda
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error al guardar: {str(e)}")


# --- SUCURSALES ---
@router.get("/sucursales")
def obtener_sucursales(db: Session = Depends(get_db)):
    return db.query(Sucursal).all()

@router.post("/sucursales")
def crear_sucursal(
    sucursal: SucursalCreate, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nueva_sucursal = Sucursal(
        nombre=sucursal.nombre, 
        direccion=sucursal.direccion
    )
    db.add(nueva_sucursal)
    db.commit()
    db.refresh(nueva_sucursal)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "sucursales", nueva_sucursal.id, f"Se creó la sucursal: {nueva_sucursal.nombre}")
    
    return nueva_sucursal


@router.post("/variantes-stock")
def registrar_variante_y_stock(
    datos: VarianteStockCreate, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nueva_variante = VariantePrenda(
        prenda_id=datos.prenda_id,
        talla=datos.talla,
        color=datos.color,
        codigo_sku=datos.codigo_sku
    )
    db.add(nueva_variante)
    db.flush() 
    
    nuevo_inventario = Inventario(
        variante_id=nueva_variante.id,
        sucursal_id=datos.sucursal_id,
        stock_disponible=datos.cantidad,
        stock_reservado=0
    )
    db.add(nuevo_inventario)
    db.commit()
    
    # AUDITORÍA (Asociada al inventario)
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "inventario", nuevo_inventario.id, f"Se agregó stock para SKU: {datos.codigo_sku}")
    
    return {"mensaje": "Variante y stock registrados correctamente", "sku": datos.codigo_sku}


# --- CATEGORÍAS ---
@router.get("/categorias", response_model=List[CategoriaResponse])
def obtener_categorias(db: Session = Depends(get_db)):
    return db.query(Categoria).all()

@router.post("/categorias", response_model=CategoriaResponse)
def crear_categoria(
    categoria: CategoriaBase, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nueva_categoria = Categoria(nombre=categoria.nombre)
    db.add(nueva_categoria)
    db.commit()
    db.refresh(nueva_categoria)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "categorias", nueva_categoria.id, f"Se creó la categoría: {nueva_categoria.nombre}")
    
    return nueva_categoria


# --- PROVEEDORES ---
@router.get("/proveedores", response_model=List[ProveedorResponse])
def obtener_proveedores(db: Session = Depends(get_db)):
    return db.query(Proveedor).all()

@router.post("/proveedores")
def crear_proveedor(
    proveedor: ProveedorCreate, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nuevo_proveedor = Proveedor(razon_social=proveedor.nombre)
    db.add(nuevo_proveedor)
    db.commit()
    db.refresh(nuevo_proveedor)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "proveedores", nuevo_proveedor.id, f"Se registró el proveedor: {nuevo_proveedor.razon_social}")
    
    return nuevo_proveedor


@router.get("/colecciones", response_model=List[ColeccionResponse])
def obtener_colecciones(db: Session = Depends(get_db)):
    return db.query(Coleccion).all()

@router.post("/colecciones", response_model=ColeccionResponse)
def crear_coleccion(
    coleccion: ColeccionBase, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nueva_coleccion = Coleccion(
        nombre=coleccion.nombre,
        descripcion=coleccion.descripcion
    )
    db.add(nueva_coleccion)
    db.commit()
    db.refresh(nueva_coleccion)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "colecciones", nueva_coleccion.id, f"Se creó la colección: {nueva_coleccion.nombre}")
    
    return nueva_coleccion

# --- TEMPORADAS ---
# (Movido aquí arriba, antes de las rutas dinámicas)
@router.get("/temporadas", response_model=List[TemporadaResponse])
def obtener_temporadas(db: Session = Depends(get_db)):
    return db.query(Temporada).all()

@router.post("/temporadas", response_model=TemporadaResponse)
def crear_temporada(
    temporada: TemporadaBase, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nueva_temporada = Temporada(
        nombre=temporada.nombre,
        fecha_inicio=temporada.fecha_inicio,
        fecha_fin=temporada.fecha_fin
    )
    db.add(nueva_temporada)
    db.commit()
    db.refresh(nueva_temporada)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "temporadas", nueva_temporada.id, f"Se creó la temporada: {nueva_temporada.nombre}")
    
    return nueva_temporada

@router.get("/{prenda_id}/variantes")
def obtener_variantes_prenda(prenda_id: int, db: Session = Depends(get_db)):
    # Buscamos todas las variantes de esta prenda
    variantes = db.query(VariantePrenda).filter(VariantePrenda.prenda_id == prenda_id).all()
    
    resultado = []
    for v in variantes:
        # Sumamos el stock de esta variante en todas las sucursales
        stock = db.query(func.sum(Inventario.stock_disponible)).filter(Inventario.variante_id == v.id).scalar() or 0
        resultado.append({
            "id": v.id,
            "talla": v.talla,
            "color": v.color,
            "sku": v.codigo_sku,
            "stock": stock
        })
    return resultado

# ==========================================
# 3. RUTAS DINÁMICAS
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
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
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
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "MODIFICAR", "prendas", prenda.id, f"Se editó la prenda con ID: {prenda.id}")
    
    return prenda

@router.delete("/{prenda_id}")
def eliminar_prenda(
    prenda_id: int, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    prenda = db.query(Prenda).filter(Prenda.id == prenda_id).first()
    if not prenda:
        raise HTTPException(status_code=404, detail="Prenda no encontrada")
    
    db.delete(prenda)
    db.commit()
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "ELIMINAR", "prendas", prenda_id, f"Se eliminó la prenda con ID: {prenda_id}")
    
    return {"mensaje": "Prenda eliminada con éxito"}

@router.get("/dashboard/resumen")
def obtener_resumen_dashboard(
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    total_prendas = db.query(Prenda).count()
    total_sucursales = db.query(Sucursal).count()
    total_proveedores = db.query(Proveedor).count()
    total_categorias = db.query(Categoria).count()
    
    # Sumamos todo el stock disponible en todas las sucursales
    stock_total = db.query(func.sum(Inventario.stock_disponible)).scalar() or 0
    
    return {
        "total_prendas": total_prendas,
        "total_sucursales": total_sucursales,
        "total_proveedores": total_proveedores,
        "total_categorias": total_categorias,
        "stock_total": stock_total
    }
    
@router.get("/parche-db")
def arreglar_descripcion_prendas():
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE prendas ALTER COLUMN descripcion TYPE TEXT;"))
        return {"mensaje": "¡Columna descripción ampliada con éxito! Ya puedes guardar textos largos."}
    except Exception as e:
        return {"error": str(e)}