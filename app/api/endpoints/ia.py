import os
import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.database import SessionLocal
# Ajusta estas importaciones según cómo se llamen tus modelos reales
from app.models.inventario import Prenda, Sucursal, Categoria, Inventario 
from app.models.reservas import Orden

router = APIRouter()

class VozRequest(BaseModel):
    texto_voz: str

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/generar-reporte")
def generar_reporte_ia(request: VozRequest, db: Session = Depends(get_db)):
    # 1. Configurar la llave de Gemini
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Falta configurar GEMINI_API_KEY en el entorno")
    
    genai.configure(api_key=api_key)
    # Usamos Flash porque es la versión más rápida y gratuita
    model = genai.GenerativeModel('gemini-1.5-flash')

    # 2. Recopilar datos rápidos de tu Base de Datos para darle contexto a la IA
    total_prendas = db.query(Prenda).count()
    stock_total = db.query(func.sum(Inventario.stock_disponible)).scalar() or 0
    
    # Calculamos el total de dinero en órdenes completadas (Ventas reales)
    ingresos_totales = db.query(func.sum(Orden.total)).filter(Orden.estado == "COMPLETADO").scalar() or 0

    # 3. Armar el Prompt (El secreto para que la IA responda bien)
    prompt = f"""
    Actúa como un analista experto en retail para la cadena de ropa 'FashionStore'.
    
    Aquí tienes los datos reales actuales de la base de datos:
    - Total de modelos en catálogo: {total_prendas}
    - Stock físico global disponible: {stock_total} unidades
    - Ingresos totales generados: {ingresos_totales} Bs.
    
    El administrador del sistema te ha pedido lo siguiente a través de un comando de voz: 
    "{request.texto_voz}"
    
    Tu tarea: 
    Responde a su petición utilizando LOS DATOS REALES que te proporcioné.
    Sé directo, profesional y conciso (máximo 2 o 3 párrafos cortos). 
    Utiliza formato Markdown (negritas, viñetas) para que sea fácil de leer en la pantalla.
    """
    
    # 4. Enviar a Gemini y devolver el texto
    try:
        respuesta = model.generate_content(prompt)
        return {"reporte": respuesta.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con la IA: {str(e)}")