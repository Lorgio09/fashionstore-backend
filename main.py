from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.endpoints import reservas, catalogo, usuarios, auditoria

# NUEVO: INICIALIZACIÓN DE LA BASE DE DATOS
from app.db.database import engine, Base
# Importamos el modelo para que SQLAlchemy sepa que existe y debe crearlo.
from app.models.auditoria import Bitacora 

# Esta es la orden mágica que crea la tabla "bitacora" en PostgreSQL si no existe
Base.metadata.create_all(bind=engine)
# ==========================================

app = FastAPI(title="FashionStore API")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(usuarios.router, prefix="/api/usuarios", tags=["Usuarios"])

origins = [
    "http://localhost:4200",     # Permite a tu servidor de Angular local
    "http://127.0.0.1:4200",
    "https://fashionstore-web.onrender.com" # Alternativa de localhost
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,      
    allow_credentials=True,
    allow_methods=["*"],         
    allow_headers=["*"],         
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(usuarios.router, prefix="/api/usuarios", tags=["Usuarios"])
app.include_router(catalogo.router, prefix="/api/catalogo", tags=["Catálogo"])
app.include_router(reservas.router, prefix="/api/reservas", tags=["Reservas"])
app.include_router(auditoria.router, prefix="/api/auditoria", tags=["Auditoría"])

@app.get("/")
def estado_servidor():
    return {"estado": "API de FashionStore en línea y funcionando"}