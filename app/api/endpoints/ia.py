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
    # 1. Validar la clave de Gemini
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500, 
            detail="Falta configurar la variable de entorno GEMINI_API_KEY"
        )
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

    # 2. Recopilar métricas en tiempo real desde PostgreSQL
    total_prendas = db.query(Prenda).count()
    total_sucursales = db.query(Sucursal).count()
    total_categorias = db.query(Categoria).count()
    stock_total = db.query(func.sum(Inventario.stock_disponible)).scalar() or 0
    total_reservas = db.query(Reserva).count()
    
    # Suma de órdenes completadas / pagadas
    ingresos_totales = db.query(func.sum(Orden.total)).filter(
        (Orden.estado == "COMPLETADO") | (Orden.estado == "PAGADO")
    ).scalar() or 0.0

    # 3. Prompt estructurado para análisis de retail
    prompt = f"""
    Actúa como el consultor y analista de negocios de 'FashionStore'.
    
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
    3. Incluye una breve recomendación estratégica o de alerta si el stock o las ventas lo ameritan.
    4. Usa formato Markdown limpio (viñetas y negritas).
    """
    
    # 4. Invocación al modelo generativo
    try:
        respuesta = model.generate_content(prompt)
        return {"reporte": respuesta.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con el servicio de IA: {str(e)}")