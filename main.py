from fastapi import FastAPI

app = FastAPI(title="FashionStore API")

@app.get("/")
def estado_servidor():
    return {"estado": "API de FashionStore en línea y funcionando"}