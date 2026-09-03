from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import reservas, catalogo, usuarios
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="FashionStore API")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(usuarios.router, prefix="/api/usuarios", tags=["Usuarios"])

origins = [
    "http://localhost:4200",     # Permite a tu servidor de Angular local
    "http://127.0.0.1:4200",     # Alternativa de localhost
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],         # Permite todos los métodos (GET, POST, PUT, DELETE)
    allow_headers=["*"],         # Permite todos los headers
)

# Registrar los routers
app.include_router(catalogo.router, prefix="/api/catalogo", tags=["Catálogo"])
app.include_router(reservas.router, prefix="/api/reservas", tags=["Reservas"])

@app.get("/")
def estado_servidor():
    return {"estado": "API de FashionStore en línea y funcionando"}