import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.endpoints import auditoria, catalogo, empresa, ia, plataforma, reservas, usuarios
from app.db.database import Base, engine
from app.db.tenant import AccesoCruzado, TenantNoDefinido
from app import models as _modelos  # noqa: F401  (registra todos los modelos)

logger = logging.getLogger("fashionstore")

# Crea las tablas que no existan. Los cambios de columnas se aplican con Alembic
# (alembic upgrade head) antes de iniciar el servidor.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="FashionStore SaaS API")

# 1. CORS Middleware SIEMPRE va primero
origins = [
    "http://localhost:4200",
    "http://127.0.0.1:4200",
    "https://fashionstore-web.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 2. Errores de aislamiento multitenant
@app.exception_handler(AccesoCruzado)
def _acceso_cruzado(request: Request, exc: AccesoCruzado):
    logger.warning("Acceso cruzado bloqueado en %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=403, content={"detail": "No tiene acceso a recursos de otra empresa"})


@app.exception_handler(TenantNoDefinido)
def _tenant_no_definido(request: Request, exc: TenantNoDefinido):
    logger.error("Consulta sin contexto de empresa en %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Error interno: operación sin contexto de empresa"})


# 3. Rutas y archivos estáticos van DESPUÉS
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(usuarios.router, prefix="/api/usuarios", tags=["Usuarios"])
app.include_router(catalogo.router, prefix="/api/catalogo", tags=["Catálogo"])
app.include_router(reservas.router, prefix="/api/reservas", tags=["Reservas"])
app.include_router(auditoria.router, prefix="/api/auditoria", tags=["Auditoría"])
app.include_router(ia.router, prefix="/api/ia", tags=["Inteligencia Artificial"])
app.include_router(empresa.router, prefix="/api/empresa", tags=["Mi empresa (tenant)"])
app.include_router(plataforma.router, prefix="/api/plataforma", tags=["Plataforma SaaS"])


@app.get("/")
def estado_servidor():
    return {"estado": "API de FashionStore en línea y funcionando"}
