from fastapi import FastAPI
from app.api.endpoints import reservas, catalogo

app = FastAPI(title="FashionStore API")

# Registrar los routers
app.include_router(catalogo.router, prefix="/api/catalogo", tags=["Catálogo"])
app.include_router(reservas.router, prefix="/api/reservas", tags=["Reservas"])

@app.get("/")
def estado_servidor():
    return {"estado": "API de FashionStore en línea y funcionando"}