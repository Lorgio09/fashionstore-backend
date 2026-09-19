from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.models.reservas import Reserva, DetalleReserva
from app.models.inventario import Inventario 
from app.schemas.reservas import ReservaCreate, ReservaResponse
from typing import List

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 1. CREAR RESERVA (Con validación y descuento de stock)
@router.post("/", response_model=ReservaResponse)
def crear_reserva(reserva: ReservaCreate, db: Session = Depends(get_db)):
    # Validar stock ANTES de crear la reserva
    for detalle in reserva.detalles:
        inventario = db.query(Inventario).filter(
            Inventario.sucursal_id == reserva.sucursal_id,
            Inventario.variante_id == detalle.variante_id
        ).first()

        if not inventario or inventario.stock_disponible < detalle.cantidad:
            raise HTTPException(
                status_code=400, 
                detail=f"Stock insuficiente para la variante {detalle.variante_id} en esta sucursal."
            )

    # Crear cabecera
    nueva_reserva = Reserva(
        fecha_visita=reserva.fecha_visita,
        cliente_id=reserva.cliente_id,
        sucursal_id=reserva.sucursal_id,
        estado="Pendiente"
    )
    db.add(nueva_reserva)
    db.flush() # Obtenemos el ID sin hacer commit total

    # Registrar detalles y DESCONTAR stock
    for detalle in reserva.detalles:
        nuevo_detalle = DetalleReserva(
            reserva_id=nueva_reserva.id,
            variante_id=detalle.variante_id,
            cantidad=detalle.cantidad
        )
        db.add(nuevo_detalle)

        # Descontamos el stock físico para que nadie más lo compre
        inventario = db.query(Inventario).filter(
            Inventario.sucursal_id == reserva.sucursal_id,
            Inventario.variante_id == detalle.variante_id
        ).first()
        inventario.stock_disponible -= detalle.cantidad

    db.commit()
    db.refresh(nueva_reserva)
    return nueva_reserva

# 2. LISTAR RESERVAS POR SUCURSAL (Para el Encargado)
@router.get("/sucursal/{sucursal_id}")
def obtener_reservas_sucursal(sucursal_id: int, db: Session = Depends(get_db)):
    reservas = db.query(Reserva).filter(Reserva.sucursal_id == sucursal_id).order_by(Reserva.fecha_visita.asc()).all()
    return reservas

# 3. LISTAR RESERVAS DEL CLIENTE (Para el historial en la Web/Móvil)
@router.get("/cliente/{cliente_id}")
def obtener_reservas_cliente(cliente_id: int, db: Session = Depends(get_db)):
    reservas = db.query(Reserva).filter(Reserva.cliente_id == cliente_id).order_by(Reserva.fecha_creacion.desc()).all()
    return reservas

# 4. ACTUALIZAR ESTADO DE LA RESERVA (Preparada, Completada, Cancelada)
@router.put("/{reserva_id}/estado")
def actualizar_estado_reserva(reserva_id: int, nuevo_estado: str, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.id == reserva_id).first()
    if not reserva:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")

    estados_validos = ["Pendiente", "Preparada", "Completada", "Cancelada"]
    if nuevo_estado not in estados_validos:
        raise HTTPException(status_code=400, detail="Estado no válido")

    # Si se cancela, debemos DEVOLVER el stock al inventario
    if nuevo_estado == "Cancelada" and reserva.estado != "Cancelada":
        for detalle in reserva.detalles:
            inventario = db.query(Inventario).filter(
                Inventario.sucursal_id == reserva.sucursal_id,
                Inventario.variante_id == detalle.variante_id
            ).first()
            if inventario:
                inventario.stock_disponible += detalle.cantidad

    reserva.estado = nuevo_estado
    db.commit()
    
    return {"mensaje": f"Reserva actualizada a {nuevo_estado}"}