"""
Pruebas automatizadas con una base SQLite temporal (no toca PostgreSQL).
Cada prueba arranca con dos empresas independientes (RN04):
  - Empresa A: plan Profesional
  - Empresa B: plan Básico
"""
import os
import tempfile

_DIR = tempfile.mkdtemp(prefix="fashionstore-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_DIR, 'test.db')}"
os.environ["EMPRESA_PUBLICA_POR_DEFECTO"] = "empresa-a"
os.environ["GEMINI_API_KEY"] = ""  # las pruebas nunca llaman al proveedor de IA (se simula)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.db.database import Base, SessionLocal, engine  # noqa: E402
from app.db.tenant import set_global  # noqa: E402
from app.models.inventario import Categoria, Inventario, Prenda, Proveedor, Sucursal, VariantePrenda  # noqa: E402
from app.models.saas import Empresa, Plan  # noqa: E402
from app.models.usuarios import (  # noqa: E402
    ROL_ADMIN_EMPRESA, ROL_ADMIN_PLATAFORMA, ROL_CAJERO, ROL_CLIENTE, ROL_ENCARGADO, Rol, Usuario,
)
from app.services import suscripciones as svc  # noqa: E402

CLAVE = "Clave123!"
_HASH = get_password_hash(CLAVE)


def _sembrar() -> dict:
    db = SessionLocal()
    set_global(db)
    roles = {n: Rol(nombre=n) for n in (ROL_CLIENTE, ROL_ADMIN_EMPRESA, ROL_ENCARGADO, ROL_CAJERO, ROL_ADMIN_PLATAFORMA)}
    db.add_all(roles.values())
    basico = Plan(codigo="BASICO", nombre="Básico", max_sucursales=2, permite_reportes_ia=False)
    pro = Plan(codigo="PROFESIONAL", nombre="Profesional", max_sucursales=10, permite_reportes_ia=True)
    db.add_all([basico, pro])
    db.flush()

    db.add(Usuario(email="plataforma@test.com", nombre_completo="Plataforma", password_hash=_HASH,
                   rol_id=roles[ROL_ADMIN_PLATAFORMA].id))
    datos = {}
    for clave, plan in (("a", pro), ("b", basico)):
        e = Empresa(razon_social=f"Empresa {clave.upper()}", nit=f"NIT-{clave}", slug=f"empresa-{clave}")
        db.add(e)
        db.flush()
        svc.asignar_plan(db, e.id, plan, "ANUAL")
        suc = Sucursal(nombre=f"Sucursal {clave}", empresa_id=e.id)
        cat = Categoria(nombre=f"Categoria {clave}", empresa_id=e.id)
        prov = Proveedor(razon_social=f"Proveedor {clave}", empresa_id=e.id)
        db.add_all([suc, cat, prov])
        db.flush()
        prenda = Prenda(nombre=f"Prenda {clave}", precio_base=100, categoria_id=cat.id, proveedor_id=prov.id, empresa_id=e.id)
        db.add(prenda)
        db.flush()
        var = VariantePrenda(prenda_id=prenda.id, talla="M", color="Negro", codigo_sku="SKU-1", empresa_id=e.id)
        db.add(var)
        db.flush()
        db.add(Inventario(variante_id=var.id, sucursal_id=suc.id, stock_disponible=10, stock_reservado=0, empresa_id=e.id))
        for rol, email in ((ROL_ADMIN_EMPRESA, f"admin@{clave}.com"), (ROL_CAJERO, f"cajero@{clave}.com"),
                           (ROL_CLIENTE, f"cliente@{clave}.com")):
            db.add(Usuario(email=email, nombre_completo=email, password_hash=_HASH, rol_id=roles[rol].id,
                           empresa_id=e.id, sucursal_id=suc.id if rol == ROL_CAJERO else None))
        db.flush()
        datos[clave] = {"empresa": e.id, "slug": e.slug, "sucursal": suc.id, "categoria": cat.id,
                        "proveedor": prov.id, "prenda": prenda.id, "variante": var.id}
    db.commit()
    db.close()
    return datos


@pytest.fixture()
def datos():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return _sembrar()


@pytest.fixture()
def client(datos):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def token(client):
    cache = {}

    def _token(email: str) -> dict:
        if email not in cache:
            r = client.post("/api/usuarios/login", json={"email": email, "password": CLAVE})
            assert r.status_code == 200, r.text
            cache[email] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return cache[email]

    return _token
