"""
Datos de demostración del SaaS (idempotente: se puede ejecutar varias veces).

    python -m scripts.seed_demo

Crea:
- Roles base y el Administrador de plataforma.
- Empresa 1 "FashionStore" (plan Profesional): la creada por la migración con los datos originales.
- Empresa 2 "Moda Andina" (plan Básico): administrador, cajero, 1 sucursal, catálogo y stock.

Contraseña de los usuarios demo: variable SEED_PASSWORD (por defecto FashionStore2026!).
"""
import os
import sys

from app import models  # noqa: F401
from app.core.security import get_password_hash
from app.db.database import SessionLocal
from app.db.tenant import set_global
from app.models.inventario import Categoria, Inventario, Prenda, Proveedor, Sucursal, VariantePrenda
from app.models.saas import Empresa, Plan
from app.models.usuarios import (
    ROL_ADMIN_EMPRESA,
    ROL_ADMIN_PLATAFORMA,
    ROL_CAJERO,
    ROL_CLIENTE,
    ROL_ENCARGADO,
    Rol,
    Usuario,
)
from app.services import suscripciones as svc

PASSWORD = os.getenv("SEED_PASSWORD", "FashionStore2026!")

ROLES = [
    (ROL_CLIENTE, "Cliente de una tienda"),
    (ROL_ADMIN_EMPRESA, "Administrador de una empresa contratante"),
    (ROL_ENCARGADO, "Encargado de una sucursal"),
    (ROL_CAJERO, "Cajero de una sucursal"),
    (ROL_ADMIN_PLATAFORMA, "Proveedor del servicio SaaS"),
]

PLANES = [
    dict(codigo="BASICO", nombre="Básico", precio_mensual=150, max_sucursales=2, permite_reportes_ia=False),
    dict(codigo="PROFESIONAL", nombre="Profesional", precio_mensual=450, max_sucursales=10, permite_reportes_ia=True),
]

CATALOGO_MODA_ANDINA = [
    # categoria, prenda, precio, [(talla, color, stock)]
    ("Poleras", "Polera Andina Algodón", 89.0, [("S", "Blanco", 12), ("M", "Blanco", 15), ("L", "Negro", 8)]),
    ("Poleras", "Polera Estampada Illimani", 110.0, [("M", "Azul", 10), ("L", "Azul", 6)]),
    ("Pantalones", "Jean Slim Tarija", 240.0, [("30", "Azul", 7), ("32", "Azul", 9), ("34", "Negro", 4)]),
    ("Chamarras", "Chamarra Alpaca", 520.0, [("M", "Café", 3), ("L", "Gris", 2)]),
]


def _rol(db, nombre):
    return db.query(Rol).filter(Rol.nombre == nombre).one()


def _usuario(db, email, nombre, rol, empresa_id=None, sucursal_id=None):
    u = db.query(Usuario).filter(Usuario.email == email).first()
    if u is None:
        u = Usuario(
            email=email,
            nombre_completo=nombre,
            password_hash=get_password_hash(PASSWORD),
            rol_id=_rol(db, rol).id,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
        )
        db.add(u)
        db.flush()
        print(f"  + usuario {email} ({rol})")
    return u


def _empresa(db, slug, razon_social, nit, plan_codigo):
    e = db.query(Empresa).filter(Empresa.slug == slug).first()
    if e is None:
        e = Empresa(slug=slug, razon_social=razon_social, nit=nit, estado="ACTIVA")
        db.add(e)
        db.flush()
        print(f"  + empresa {slug}")
    if svc.suscripcion_actual(db, e.id) is None:
        plan = db.query(Plan).filter(Plan.codigo == plan_codigo).one()
        svc.asignar_plan(db, e.id, plan, "ANUAL")
        print(f"  + suscripción {slug} -> {plan_codigo}")
    return e


def main():
    db = SessionLocal()
    set_global(db)
    try:
        for nombre, desc in ROLES:
            if not db.query(Rol).filter(Rol.nombre == nombre).first():
                db.add(Rol(nombre=nombre, descripcion=desc))
        for p in PLANES:
            if not db.query(Plan).filter(Plan.codigo == p["codigo"]).first():
                db.add(Plan(**p))
        db.flush()

        _usuario(db, "plataforma@fashionstore.com", "Administrador de Plataforma", ROL_ADMIN_PLATAFORMA)

        # Empresa 1: la original (la migración ya le asignó todos los datos existentes)
        fs = _empresa(db, "fashionstore", "FashionStore S.R.L.", "1000000001", "PROFESIONAL")
        tiene_admin = (
            db.query(Usuario).join(Rol)
            .filter(Usuario.empresa_id == fs.id, Rol.nombre == ROL_ADMIN_EMPRESA).first()
        )
        if not tiene_admin:
            _usuario(db, "admin@fashionstore.com", "Admin FashionStore", ROL_ADMIN_EMPRESA, fs.id)

        # Empresa 2: Moda Andina, plan Básico
        ma = _empresa(db, "moda-andina", "Moda Andina S.R.L.", "2000000002", "BASICO")
        suc = db.query(Sucursal).filter(Sucursal.empresa_id == ma.id).first()
        if suc is None:
            suc = Sucursal(nombre="Moda Andina - Centro", direccion="Calle Sucre 120, La Paz", empresa_id=ma.id)
            db.add(suc)
            db.flush()
            print("  + sucursal Moda Andina - Centro")
        _usuario(db, "admin@modaandina.com", "Admin Moda Andina", ROL_ADMIN_EMPRESA, ma.id)
        _usuario(db, "cajero@modaandina.com", "Cajero Moda Andina", ROL_CAJERO, ma.id, suc.id)
        _usuario(db, "cliente@modaandina.com", "Cliente Moda Andina", ROL_CLIENTE, ma.id)

        if not db.query(Prenda).filter(Prenda.empresa_id == ma.id).first():
            proveedor = Proveedor(razon_social="Textiles del Altiplano", empresa_id=ma.id)
            db.add(proveedor)
            categorias = {}
            for nombre_cat, nombre, precio, variantes in CATALOGO_MODA_ANDINA:
                if nombre_cat not in categorias:
                    categorias[nombre_cat] = Categoria(nombre=nombre_cat, empresa_id=ma.id)
                    db.add(categorias[nombre_cat])
                db.flush()
                prenda = Prenda(
                    nombre=nombre, precio_base=precio, descripcion=f"{nombre} - colección Moda Andina",
                    categoria_id=categorias[nombre_cat].id, proveedor_id=proveedor.id, empresa_id=ma.id,
                )
                db.add(prenda)
                db.flush()
                for talla, color, stock in variantes:
                    sku = f"MA-{prenda.id}-{talla}-{color[:3].upper()}"
                    v = VariantePrenda(prenda_id=prenda.id, talla=talla, color=color, codigo_sku=sku, empresa_id=ma.id)
                    db.add(v)
                    db.flush()
                    db.add(Inventario(variante_id=v.id, sucursal_id=suc.id, stock_disponible=stock,
                                      stock_reservado=0, empresa_id=ma.id))
            print("  + catálogo Moda Andina")

        db.commit()
        print(f"\nListo. Contraseña de los usuarios demo: {PASSWORD}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
