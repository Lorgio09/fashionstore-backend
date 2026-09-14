from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.endpoints import reservas, catalogo, usuarios, auditoria
from app.db.database import engine, Base
from app.models.auditoria import Bitacora 

# Inicialización de la BD
Base.metadata.create_all(bind=engine)

app = FastAPI(title="FashionStore API")

# 1. CORS Middleware SIEMPRE va primero
origins = [
    "http://localhost:4200",     
    "http://127.0.0.1:4200",
    "https://fashionstore-web.onrender.com" 
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,      
    allow_credentials=True,
    allow_methods=["*"],         
    allow_headers=["*"],         
)

# 2. Rutas y archivos estáticos van DESPUÉS
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(usuarios.router, prefix="/api/usuarios", tags=["Usuarios"])
app.include_router(catalogo.router, prefix="/api/catalogo", tags=["Catálogo"])
app.include_router(reservas.router, prefix="/api/reservas", tags=["Reservas"])
app.include_router(auditoria.router, prefix="/api/auditoria", tags=["Auditoría"])

@app.get("/")
def estado_servidor():
    return {"estado": "API de FashionStore en línea y funcionando"}