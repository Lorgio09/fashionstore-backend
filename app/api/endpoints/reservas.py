from fastapi import APIRouter, Depends, HTTPException

from app.core.contexto import ROLES_PERSONAL, Contexto, get_contexto, requiere_roles
from app.models.inventario import Inventario, Sucursal
from app.models.reservas import Reserva, DetalleReserva
from app.models.usuarios import ROL_CLIENTE, Usuario
from app.schemas.reservas import ReservaCreate, ReservaResponse
from app.services.validaciones import obtener_o_404, validar_variantes

router = APIRouter()


# 1. CREAR RESERVA (Con validación y descuento de stock)
@router.post("/", response_model=ReservaResponse)
def crear_reserva(reserva: ReservaCreate, ctx: Contexto = Depends(get_contexto)):
    db = ctx.db
    # Un cliente solo reserva para sí mismo; el personal puede reservar para un cliente de la empresa.
    if ctx.rol == ROL_CLIENTE:
        cliente_id = ctx.usuario.id
    else:
        if reserva.cliente_id is None:
            raise HTTPException(status_code=422, detail="Debe indicar el cliente de la reserva")
        cliente_id = obtener_o_404(db, Usuario, reserva.cliente_id, "Cliente").id

    sucursal = obtener_o_404(db, Sucursal, reserva.sucursal_id, "Sucursal")
    if not sucursal.activa:
        raise HTTPException(status_code=409, detail="La sucursal está inactiva")
    if any(d.cantidad <= 0 for d in reserva.detalles):
        raise HTTPException(status_code=422, detail="Las cantidades deben ser mayores a cero")
    validar_variantes(db, [d.variante_id for d in reserva.detalles])

    # Validar y bloquear el stock ANTES de crear la reserva (RN12)
    inventarios = {}
    for detalle in reserva.detalles:
        inventario = db.query(Inventario).filter(
            Inventario.sucursal_id == reserva.sucursal_id,
            Inventario.variante_id == detalle.variante_id
        ).with_for_update().first()

        if not inventario or inventario.stock_disponible < detalle.cantidad:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Stock insuficiente para la variante {detalle.variante_id} en esta sucursal."
            )
        inventarios[detalle.variante_id] = inventario

    nueva_reserva = Reserva(
        fecha_visita=reserva.fecha_visita,
        cliente_id=cliente_id,
        sucursal_id=reserva.sucursal_id,
        usuario_id=None if ctx.rol == ROL_CLIENTE else ctx.usuario.id,
        estado="Pendiente"
    )
    db.add(nueva_reserva)
    db.flush()

    # Registrar detalles y DESCONTAR stock para que nadie más lo compre
    for detalle in reserva.detalles:
        db.add(DetalleReserva(
            reserva_id=nueva_reserva.id,
            variante_id=detalle.variante_id,
            cantidad=detalle.cantidad
        ))
        inventarios[detalle.variante_id].stock_disponible -= detalle.cantidad

    db.commit()
    db.refresh(nueva_reserva)
    return nueva_reserva


# 2. LISTAR RESERVAS POR SUCURSAL (Para el Encargado)
@router.get("/sucursal/{sucursal_id}")
def obtener_reservas_sucursal(sucursal_id: int, ctx: Contexto = Depends(requiere_roles(*ROLES_PERSONAL))):
    return ctx.db.query(Reserva).filter(Reserva.sucursal_id == sucursal_id).order_by(Reserva.fecha_visita.asc()).all()


# 3. LISTAR RESERVAS DEL CLIENTE (Para el historial en la Web/Móvil)
@router.get("/cliente/{cliente_id}")
def obtener_reservas_cliente(cliente_id: int, ctx: Contexto = Depends(get_contexto)):
    if ctx.rol == ROL_CLIENTE and cliente_id != ctx.usuario.id:
        raise HTTPException(status_code=403, detail="Solo puede consultar sus propias reservas")
    return ctx.db.query(Reserva).filter(Reserva.cliente_id == cliente_id).order_by(Reserva.fecha_creacion.desc()).all()


# 4. ACTUALIZAR ESTADO DE LA RESERVA (Preparada, Completada, Cancelada)
@router.put("/{reserva_id}/estado")
def actualizar_estado_reserva(reserva_id: int, nuevo_estado: str, ctx: Contexto = Depends(requiere_roles(*ROLES_PERSONAL))):
    db = ctx.db
    reserva = obtener_o_404(db, Reserva, reserva_id, "Reserva")

    estados_validos = ["Pendiente", "Preparada", "Completada", "Cancelada"]
    if nuevo_estado not in estados_validos:
        raise HTTPException(status_code=400, detail="Estado no válido")

    # Si se cancela, debemos DEVOLVER el stock al inventario
    if nuevo_estado == "Cancelada" and reserva.estado != "Cancelada":
        for detalle in reserva.detalles:
            inventario = db.query(Inventario).filter(
                Inventario.sucursal_id == reserva.sucursal_id,
                Inventario.variante_id == detalle.variante_id
            ).with_for_update().first()
            if inventario:
                inventario.stock_disponible += detalle.cantidad

    reserva.estado = nuevo_estado
    db.commit()

    return {"mensaje": f"Reserva actualizada a {nuevo_estado}"}
