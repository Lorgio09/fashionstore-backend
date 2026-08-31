from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.models.reservas import Reserva, DetalleReserva
from app.schemas.reservas import ReservaCreate, ReservaResponse

router = APIRouter()

# Dependencia para gestionar la sesión de la base de datos
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=ReservaResponse)
def crear_reserva(reserva: ReservaCreate, db: Session = Depends(get_db)):
    # Crear la cabecera de la reserva
    nueva_reserva = Reserva(
        fecha_visita=reserva.fecha_visita,
        cliente_id=reserva.cliente_id,
        sucursal_id=reserva.sucursal_id
    )
    db.add(nueva_reserva)
    db.commit()
    db.refresh(nueva_reserva)

    #  Registrar los detalles (las prendas específicas)
    for detalle in reserva.detalles:
        nuevo_detalle = DetalleReserva(
            reserva_id=nueva_reserva.id,
            variante_id=detalle.variante_id,
            cantidad=detalle.cantidad
        )
        db.add(nuevo_detalle)
    
    db.commit()
    db.refresh(nueva_reserva)

    return nueva_reserva