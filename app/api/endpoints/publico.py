"""
Cara pública de la plataforma SaaS (sin token): directorio de tiendas y planes.

FashionStore es el proveedor; cada empresa contratante es una tienda con su propio nombre (slug).
La portada de la web y la app móvil usan esto para que el visitante elija la tienda; después el
catálogo se pide con el header ``X-Empresa: <slug>`` (contrato §2). Solo se exponen datos públicos.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.tenant import set_global
from app.models.inventario import Categoria, Prenda, Sucursal
from app.models.saas import Empresa, Plan

router = APIRouter()


class PlanPublico(BaseModel):
    codigo: str
    nombre: str
    precio_mensual: float
    max_sucursales: int
    max_usuarios: Optional[int]
    permite_offline: bool
    permite_reportes_ia: bool


class SucursalPublica(BaseModel):
    id: int
    nombre: str
    direccion: Optional[str]


class TiendaPublica(BaseModel):
    slug: str
    nombre: str
    sucursales: int
    prendas: int
    categorias: List[str]
    portada_url: Optional[str]


class TiendaDetalle(TiendaPublica):
    correo: Optional[str]
    telefono: Optional[str]
    lista_sucursales: List[SucursalPublica]


def _db_global(db: Session = Depends(get_db)) -> Session:
    # Lectura entre empresas: cada consulta filtra explícitamente por empresa_id.
    set_global(db)
    return db


def _resumen(db: Session, empresas: list[Empresa]) -> list[dict]:
    ids = [e.id for e in empresas]
    if not ids:
        return []
    sucursales = dict(db.query(Sucursal.empresa_id, func.count(Sucursal.id))
                      .filter(Sucursal.empresa_id.in_(ids), Sucursal.activa.is_(True))
                      .group_by(Sucursal.empresa_id).all())
    prendas = dict(db.query(Prenda.empresa_id, func.count(Prenda.id))
                   .filter(Prenda.empresa_id.in_(ids)).group_by(Prenda.empresa_id).all())
    portadas = {}
    for empresa_id, url in (db.query(Prenda.empresa_id, Prenda.imagen_url)
                            .filter(Prenda.empresa_id.in_(ids), Prenda.imagen_url.isnot(None), Prenda.imagen_url != "")
                            .order_by(Prenda.id)):
        portadas.setdefault(empresa_id, url)
    categorias: dict[str, list[str]] = {}
    for empresa_id, nombre in (db.query(Categoria.empresa_id, Categoria.nombre)
                               .filter(Categoria.empresa_id.in_(ids)).order_by(Categoria.nombre)):
        lista = categorias.setdefault(empresa_id, [])
        if nombre not in lista:
            lista.append(nombre)
    return [{"slug": e.slug, "nombre": e.razon_social, "sucursales": sucursales.get(e.id, 0),
             "prendas": prendas.get(e.id, 0), "categorias": categorias.get(e.id, [])[:6],
             "portada_url": portadas.get(e.id)} for e in empresas]


@router.get("/tiendas", response_model=List[TiendaPublica], summary="Directorio público de tiendas activas")
def listar_tiendas(db: Session = Depends(_db_global)):
    empresas = db.query(Empresa).filter(Empresa.estado == "ACTIVA").order_by(Empresa.razon_social).all()
    # Una empresa recién registrada, sin sucursales activas, todavía no tiene tienda que mostrar
    return [t for t in _resumen(db, empresas) if t["sucursales"] > 0]


@router.get("/tiendas/{slug}", response_model=TiendaDetalle, summary="Datos públicos de una tienda")
def obtener_tienda(slug: str, db: Session = Depends(_db_global)):
    empresa = db.query(Empresa).filter(Empresa.slug == slug.strip().lower()).first()
    if empresa is None or empresa.estado != "ACTIVA":
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    [datos] = _resumen(db, [empresa])
    lista = (db.query(Sucursal).filter(Sucursal.empresa_id == empresa.id, Sucursal.activa.is_(True))
             .order_by(Sucursal.id).all())
    return {**datos, "correo": empresa.correo, "telefono": empresa.telefono,
            "lista_sucursales": [{"id": s.id, "nombre": s.nombre, "direccion": s.direccion} for s in lista]}


@router.get("/planes", response_model=List[PlanPublico], summary="Planes de suscripción vigentes (página de precios)")
def listar_planes(db: Session = Depends(_db_global)):
    return db.query(Plan).filter(Plan.activo.is_(True)).order_by(Plan.precio_mensual, Plan.max_sucursales).all()
