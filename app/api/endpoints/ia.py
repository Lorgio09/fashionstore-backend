import os
import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.database import SessionLocal
from app.models.inventario import Prenda, Sucursal, Categoria, Inventario, Orden
from app.models.reservas import Reserva

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
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500, 
            detail="Falta configurar la variable de entorno GEMINI_API_KEY"
        )
    
    genai.configure(api_key=api_key)

    # 1. Detección automática de modelos disponibles para tu clave
    try:
        modelos_disponibles = [
            m.name for m in genai.list_models()
            if 'generateContent' in m.supported_generation_methods
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando modelos de Gemini: {str(e)}")

    if not modelos_disponibles:
        raise HTTPException(
            status_code=400, 
            detail="Tu API Key no tiene modelos de generación de texto habilitados en Google AI Studio."
        )

    # Selecciona prioritariamente cualquier modelo 'flash' disponible; si no, toma el primero válido
    modelo_elegido = next((m for m in modelos_disponibles if 'flash' in m), modelos_disponibles[0])
    model = genai.GenerativeModel(modelo_elegido)

    # 2. Recopilar métricas en tiempo real desde PostgreSQL
    total_prendas = db.query(Prenda).count()
    total_sucursales = db.query(Sucursal).count()
    total_categorias = db.query(Categoria).count()
    stock_total = db.query(func.sum(Inventario.stock_disponible)).scalar() or 0
    total_reservas = db.query(Reserva).count()
    
    ingresos_totales = db.query(func.sum(Orden.total)).filter(
        (Orden.estado == "COMPLETADO") | (Orden.estado == "PAGADO")
    ).scalar() or 0.0

    # 3. Construcción del Prompt ejecutivo
    prompt = f"""
    Actúa como consultor de negocios de 'FashionStore'.
    
    Métricas actuales del sistema:
    - Modelos de prendas registrados: {total_prendas}
    - Sucursales operativas: {total_sucursales}
    - Categorías de ropa: {total_categorias}
    - Unidades de stock físico disponibles globalmente: {stock_total}
    - Total de reservas solicitadas por clientes: {total_reservas}
    - Ingresos totales generados por ventas: Bs. {ingresos_totales:.2f}
    
    Instrucción de voz recibida del administrador:
    "{request.texto_voz}"
    
    Pautas de respuesta:
    1. Responde a la consulta basándote estrictamente en los datos provistos.
    2. Mantén un tono ejecutivo, analítico y conciso (máximo 2 a 3 párrafos).
    3. Incluye una breve recomendación sobre stock o ventas si corresponde.
    4. Usa formato Markdown limpio (viñetas y negritas).
    """
    
    # 4. Generación del reporte
    try:
        respuesta = model.generate_content(prompt)
        return {
            "reporte": respuesta.text,
            "modelo_usado": modelo_elegido
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con el servicio de IA: {str(e)}")