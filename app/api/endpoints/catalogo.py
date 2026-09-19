import os
import stripe
import shutil
import requests
from uuid import uuid4
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.db.database import SessionLocal, engine
from app.models.inventario import Prenda, Categoria, Proveedor, Sucursal, Inventario, VariantePrenda, Temporada, Coleccion, Orden, DetalleOrden
from app.models.usuarios import Usuario
from app.schemas.catalogo import PrendaResponse, PrendaCreate, CategoriaBase, CategoriaResponse, ProveedorBase, ProveedorResponse, VarianteStockCreate, TemporadaBase, TemporadaResponse,ColeccionBase,ColeccionResponse
from sqlalchemy import func,text
from app.models.inventario import Base
from app.schemas.reservas import OrdenCreate
import base64
from app.models.inventario import Categoria

# Importaciones de seguridad y auditoría
from app.core.security import get_usuario_actual, registrar_bitacora

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
router = APIRouter()
os.makedirs("static/imagenes", exist_ok=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# 1. MOLDES PYDANTIC (Schemas locales)
# ==========================================
class SucursalCreate(BaseModel):
    nombre: str
    direccion: Optional[str] = None
    
class ProveedorCreate(BaseModel):
    nombre: str

class ItemVentaPresencial(BaseModel):
    prenda_id: int
    variante_id: int
    cantidad: int
    precio: float

class VentaPresencialCreate(BaseModel):
    sucursal_id: int
    metodo_pago: str  # EFECTIVO, QR, TARJETA
    total: float
    items: List[ItemVentaPresencial]
    
class ItemCarritoCheck(BaseModel):
    variante_id: int
    cantidad: int
# ==========================================
# 2. RUTAS ESTÁTICAS
# ==========================================

# --- PRENDAS (Catálogo) ---
@router.get("/", response_model=List[PrendaResponse])
def obtener_catalogo(db: Session = Depends(get_db)):
    return db.query(Prenda).all()

@router.post("/", response_model=PrendaResponse)
def crear_prenda(
    nombre: str = Form(...),
    descripcion: str = Form(None),
    precio_base: float = Form(...),
    categoria_id: int = Form(...),
    proveedor_id: int = Form(...),
    imagen: UploadFile = File(...), 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual) # ¡Guardia!
):
    extension = imagen.filename.split(".")[-1]
    nombre_archivo = f"{uuid4()}.{extension}"
    ruta_guardado = f"static/imagenes/{nombre_archivo}"

    with open(ruta_guardado, "wb") as buffer:
        shutil.copyfileobj(imagen.file, buffer)

    url_imagen_db =f"https://fashionstore-api-kedu.onrender.com/static/imagenes/{nombre_archivo}"

    nueva_prenda = Prenda(
        nombre=nombre,
        descripcion=descripcion,
        precio_base=precio_base,
        categoria_id=categoria_id,
        proveedor_id=proveedor_id,
        imagen_url=url_imagen_db
    )
    
    try:
        db.add(nueva_prenda)
        db.commit()
        db.refresh(nueva_prenda)
        
        # AUDITORÍA
        registrar_bitacora(db, usuario_actual.id, "INSERTAR", "prendas", nueva_prenda.id, f"Se creó la prenda: {nueva_prenda.nombre}")
        
        return nueva_prenda
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error al guardar: {str(e)}")


# --- SUCURSALES ---
@router.get("/sucursales")
def obtener_sucursales(db: Session = Depends(get_db)):
    return db.query(Sucursal).all()

@router.post("/sucursales")
def crear_sucursal(
    sucursal: SucursalCreate, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nueva_sucursal = Sucursal(
        nombre=sucursal.nombre, 
        direccion=sucursal.direccion
    )
    db.add(nueva_sucursal)
    db.commit()
    db.refresh(nueva_sucursal)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "sucursales", nueva_sucursal.id, f"Se creó la sucursal: {nueva_sucursal.nombre}")
    
    return nueva_sucursal


@router.post("/variantes-stock")
def registrar_variante_y_stock(
    datos: VarianteStockCreate, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nueva_variante = VariantePrenda(
        prenda_id=datos.prenda_id,
        talla=datos.talla,
        color=datos.color,
        codigo_sku=datos.codigo_sku
    )
    db.add(nueva_variante)
    db.flush() 
    
    nuevo_inventario = Inventario(
        variante_id=nueva_variante.id,
        sucursal_id=datos.sucursal_id,
        stock_disponible=datos.cantidad,
        stock_reservado=0
    )
    db.add(nuevo_inventario)
    db.commit()
    
    # AUDITORÍA (Asociada al inventario)
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "inventario", nuevo_inventario.id, f"Se agregó stock para SKU: {datos.codigo_sku}")
    
    return {"mensaje": "Variante y stock registrados correctamente", "sku": datos.codigo_sku}


# --- CATEGORÍAS ---
@router.get("/categorias", response_model=List[CategoriaResponse])
def obtener_categorias(db: Session = Depends(get_db)):
    return db.query(Categoria).all()

@router.post("/categorias", response_model=CategoriaResponse)
def crear_categoria(
    categoria: CategoriaBase, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nueva_categoria = Categoria(nombre=categoria.nombre)
    db.add(nueva_categoria)
    db.commit()
    db.refresh(nueva_categoria)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "categorias", nueva_categoria.id, f"Se creó la categoría: {nueva_categoria.nombre}")
    
    return nueva_categoria


# --- PROVEEDORES ---
@router.get("/proveedores", response_model=List[ProveedorResponse])
def obtener_proveedores(db: Session = Depends(get_db)):
    return db.query(Proveedor).all()

@router.post("/proveedores")
def crear_proveedor(
    proveedor: ProveedorCreate, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nuevo_proveedor = Proveedor(razon_social=proveedor.nombre)
    db.add(nuevo_proveedor)
    db.commit()
    db.refresh(nuevo_proveedor)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "proveedores", nuevo_proveedor.id, f"Se registró el proveedor: {nuevo_proveedor.razon_social}")
    
    return nuevo_proveedor


@router.get("/colecciones", response_model=List[ColeccionResponse])
def obtener_colecciones(db: Session = Depends(get_db)):
    return db.query(Coleccion).all()

@router.post("/colecciones", response_model=ColeccionResponse)
def crear_coleccion(
    coleccion: ColeccionBase, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nueva_coleccion = Coleccion(
        nombre=coleccion.nombre,
        descripcion=coleccion.descripcion
    )
    db.add(nueva_coleccion)
    db.commit()
    db.refresh(nueva_coleccion)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "colecciones", nueva_coleccion.id, f"Se creó la colección: {nueva_coleccion.nombre}")
    
    return nueva_coleccion

# --- TEMPORADAS ---
# (Movido aquí arriba, antes de las rutas dinámicas)
@router.get("/temporadas", response_model=List[TemporadaResponse])
def obtener_temporadas(db: Session = Depends(get_db)):
    return db.query(Temporada).all()

@router.post("/temporadas", response_model=TemporadaResponse)
def crear_temporada(
    temporada: TemporadaBase, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    nueva_temporada = Temporada(
        nombre=temporada.nombre,
        fecha_inicio=temporada.fecha_inicio,
        fecha_fin=temporada.fecha_fin
    )
    db.add(nueva_temporada)
    db.commit()
    db.refresh(nueva_temporada)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "INSERTAR", "temporadas", nueva_temporada.id, f"Se creó la temporada: {nueva_temporada.nombre}")
    
    return nueva_temporada

@router.get("/{prenda_id}/variantes")
def obtener_variantes_prenda(prenda_id: int, db: Session = Depends(get_db)):
    # Buscamos todas las variantes de esta prenda
    variantes = db.query(VariantePrenda).filter(VariantePrenda.prenda_id == prenda_id).all()
    
    resultado = []
    for v in variantes:
        # Sumamos el stock de esta variante en todas las sucursales
        stock = db.query(func.sum(Inventario.stock_disponible)).filter(Inventario.variante_id == v.id).scalar() or 0
        resultado.append({
            "id": v.id,
            "talla": v.talla,
            "color": v.color,
            "sku": v.codigo_sku,
            "stock": stock
        })
    return resultado

@router.post("/checkout")
def procesar_compra_bcp(
    orden_datos: OrdenCreate,
    db: Session = Depends(get_db)
):
    # 1. Calcular total y guardar la orden como PENDIENTE
    total_calculado = sum(item.precio * item.cantidad for item in orden_datos.items)
    
    nueva_orden = Orden(
        nombre_cliente=orden_datos.nombre_cliente,
        correo_cliente=orden_datos.correo_cliente,
        telefono_cliente=orden_datos.telefono_cliente,
        direccion_envio=orden_datos.direccion_envio,
        total=total_calculado,
        estado="PENDIENTE"
    )
    
    try:
        db.add(nueva_orden)
        db.flush()
        
        # Guardar detalles (Aún no descontamos el stock físico del Inventario)
        for item in orden_datos.items:
            nuevo_detalle = DetalleOrden(
                orden_id=nueva_orden.id,
                prenda_id=item.prenda_id,
                variante_id=item.variante_id,
                cantidad=item.cantidad,
                precio_unitario=item.precio
            )
            db.add(nuevo_detalle)
            
        db.commit()
        db.refresh(nueva_orden)

        # 2. Extraer credenciales del entorno
        bcp_user = os.getenv('BCP_USER')
        bcp_password = os.getenv('BCP_PASSWORD')
        bcp_public_token = os.getenv('BCP_PUBLIC_TOKEN')
        bcp_app_user = os.getenv('BCP_APP_USER')
        bcp_business = os.getenv('BCP_BUSINESS_CODE')
        
        if not all([bcp_user, bcp_password, bcp_public_token, bcp_app_user, bcp_business]):
            raise ValueError("Faltan credenciales del BCP en el entorno (.env).")

        # 3. Codificar credenciales para Basic Auth
        credenciales = f"{bcp_user}:{bcp_password}"
        bcp_auth = base64.b64encode(credenciales.encode()).decode()

        # 4. Configurar la petición a la API del BCP
        url = "https://sandbox.openbanking.bcp.com.bo/Web_ApiQr/api/v4/Qr/Generated"
        headers = {
            'Content-Type': 'application/json',
            'Correlation-Id': f'FASHIONSTORE-{nueva_orden.id}', 
            'Authorization': f'Basic {bcp_auth}' 
        }
        body = {
            "appUserId": bcp_app_user,
            "currency": "BOB",
            "amount": total_calculado,
            "gloss": f"Pago de Orden {nueva_orden.id}",
            "serviceCode": "050",
            "businessCode": bcp_business,
            "singleUse": True,
            "enableBank": "ALL",
            "city": "Santa Cruz",
            "branchOffice": "Ventas Web",
            "teller": "Caja Ecommerce",
            "phoneNumber": "+591 63604323",
            "publicToken": bcp_public_token,
            "expiration": "01/02:00",
            "collectors": [
                {
                    "name": "OrdenID",
                    "parameter": "Ecommerce",
                    "value": str(nueva_orden.id)
                }
            ]
        }
        
        # 5. Ejecutar la petición usando los certificados físicos
        ruta_crt = 'certificados/bcp_cert.crt' if os.path.exists('certificados/bcp_cert.crt') else 'bcp_cert.crt'
        ruta_key = 'certificados/bcp_key.key' if os.path.exists('certificados/bcp_key.key') else 'bcp_key.key'
        cert_path = (ruta_crt, ruta_key)
        response = requests.post(url, json=body, headers=headers, cert=cert_path, verify=False, timeout=45)
        
        if response.status_code == 200:
            data = response.json().get('data', {})
            qr_base64 = data.get('qrImage')
            bcp_transaction_id = str(data.get('id'))
            
            # Devolvemos el texto base64 del QR a Angular
            return {
                "mensaje": "Orden registrada y QR generado", 
                "orden_id": nueva_orden.id,
                "qr_imagen_base64": qr_base64,
                "transaccion_bcp": bcp_transaction_id
            }
        else:
            raise ValueError(f"Error BCP: {response.text}")
            
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al procesar el pago: {str(e)}")
    
@router.post("/checkout/{orden_id}/simular-pago")
def simular_pago_orden(orden_id: int, db: Session = Depends(get_db)):
    orden = db.query(Orden).filter(Orden.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    
    if orden.estado != "PENDIENTE":
        raise HTTPException(status_code=400, detail=f"La orden ya está en estado {orden.estado}")

    # 1. Descontamos el stock físico del inventario
    for detalle in orden.detalles:
        inventario = db.query(Inventario).filter(Inventario.variante_id == detalle.variante_id).first()
        if inventario and inventario.stock_disponible >= detalle.cantidad:
            inventario.stock_disponible -= detalle.cantidad
        else:
            db.rollback()
            raise HTTPException(status_code=400, detail="Stock insuficiente en el momento de pagar.")

    # 2. Marcamos la orden como pagada
    orden.estado = "PAGADO"
    db.commit()
    
    return {"mensaje": "Pago exitoso. Stock descontado y orden actualizada.", "estado": "PAGADO"}


@router.post("/checkout/{orden_id}/simular-rechazo")
def simular_rechazo_orden(orden_id: int, db: Session = Depends(get_db)):
    orden = db.query(Orden).filter(Orden.id == orden_id).first()
    if not orden:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    
    orden.estado = "RECHAZADO"
    db.commit()
    
    return {"mensaje": "Pago rechazado. La orden fue cancelada.", "estado": "RECHAZADO"}

@router.get("/migrar-tablas-ordenes")
def crear_tablas_nuevas():
    try:
        # create_all genera las tablas que no existen, pero NO borra tus datos actuales
        Base.metadata.create_all(bind=engine)
        return {"mensaje": "¡Tablas de Órdenes y Detalles creadas exitosamente en PostgreSQL!"}
    except Exception as e:
        return {"error": str(e)}
    
@router.post("/checkout/stripe")
def procesar_compra_stripe(
    orden_datos: OrdenCreate,
    db: Session = Depends(get_db)
):
    total_calculado = sum(item.precio * item.cantidad for item in orden_datos.items)
    
    # 1. Guardar la orden como PENDIENTE
    nueva_orden = Orden(
        nombre_cliente=orden_datos.nombre_cliente,
        correo_cliente=orden_datos.correo_cliente,
        telefono_cliente=orden_datos.telefono_cliente,
        direccion_envio=orden_datos.direccion_envio,
        total=total_calculado,
        estado="PENDIENTE"
    )
    
    try:
        db.add(nueva_orden)
        db.flush()
        
        for item in orden_datos.items:
            nuevo_detalle = DetalleOrden(
                orden_id=nueva_orden.id,
                prenda_id=item.prenda_id,
                variante_id=item.variante_id,
                cantidad=item.cantidad,
                precio_unitario=item.precio
            )
            db.add(nuevo_detalle)
            
        db.commit()
        db.refresh(nueva_orden)

        # 2. Empacar los items para Stripe (exige el precio en centavos, ej: 100 Bs = 10000)
        line_items_stripe = []
        for item in orden_datos.items:
            line_items_stripe.append({
                "price_data": {
                    "currency": "bob", # O "usd" si tu cuenta de Stripe no soporta bolivianos
                    "product_data": {
                        "name": f"Prenda (ID: {item.prenda_id}, Var: {item.variante_id})",
                    },
                    "unit_amount": int(item.precio * 100), 
                },
                "quantity": item.cantidad,
            })

        # 3. Crear la sesión de pago
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items_stripe,
            mode='payment',
            # Redirecciones automáticas tras el pago
            success_url="https://fashionstore-web.onrender.com/?pago=exitoso",
            cancel_url="https://fashionstore-web.onrender.com/checkout",
            client_reference_id=str(nueva_orden.id)
        )

        return {
            "mensaje": "Sesión de Stripe creada", 
            "orden_id": nueva_orden.id,
            "url_pago": session.url
        }
            
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error con Stripe: {str(e)}")
# ==========================================
# 3. RUTAS DINÁMICAS
# ==========================================

@router.get("/{prenda_id}", response_model=PrendaResponse)
def obtener_prenda(prenda_id: int, db: Session = Depends(get_db)):
    prenda = db.query(Prenda).filter(Prenda.id == prenda_id).first()
    if not prenda:
        raise HTTPException(status_code=404, detail="Prenda no encontrada")
    return prenda

@router.put("/{prenda_id}", response_model=PrendaResponse)
def actualizar_prenda(
    prenda_id: int,
    nombre: str = Form(None),
    descripcion: str = Form(None),
    precio_base: float = Form(None),
    categoria_id: int = Form(None),
    proveedor_id: int = Form(None),
    imagen: UploadFile = File(None), 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    prenda = db.query(Prenda).filter(Prenda.id == prenda_id).first()
    if not prenda:
        raise HTTPException(status_code=404, detail="Prenda no encontrada")

    if nombre: prenda.nombre = nombre
    if descripcion: prenda.descripcion = descripcion
    if precio_base: prenda.precio_base = precio_base
    if categoria_id: prenda.categoria_id = categoria_id
    if proveedor_id: prenda.proveedor_id = proveedor_id

    if imagen:
        extension = imagen.filename.split(".")[-1]
        nombre_archivo = f"{uuid4()}.{extension}"
        ruta_guardado = f"static/imagenes/{nombre_archivo}"
        with open(ruta_guardado, "wb") as buffer:
            shutil.copyfileobj(imagen.file, buffer)
        prenda.imagen_url = f"https://fashionstore-api-kedu.onrender.com/static/imagenes/{nombre_archivo}"

    db.commit()
    db.refresh(prenda)
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "MODIFICAR", "prendas", prenda.id, f"Se editó la prenda con ID: {prenda.id}")
    
    return prenda

@router.delete("/{prenda_id}")
def eliminar_prenda(
    prenda_id: int, 
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    prenda = db.query(Prenda).filter(Prenda.id == prenda_id).first()
    if not prenda:
        raise HTTPException(status_code=404, detail="Prenda no encontrada")
    
    db.delete(prenda)
    db.commit()
    
    # AUDITORÍA
    registrar_bitacora(db, usuario_actual.id, "ELIMINAR", "prendas", prenda_id, f"Se eliminó la prenda con ID: {prenda_id}")
    
    return {"mensaje": "Prenda eliminada con éxito"}

@router.get("/dashboard/resumen")
def obtener_resumen_dashboard(
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_usuario_actual)
):
    total_prendas = db.query(Prenda).count()
    total_sucursales = db.query(Sucursal).count()
    total_proveedores = db.query(Proveedor).count()
    total_categorias = db.query(Categoria).count()
    
    # Sumamos todo el stock disponible en todas las sucursales
    stock_total = db.query(func.sum(Inventario.stock_disponible)).scalar() or 0
    
    return {
        "total_prendas": total_prendas,
        "total_sucursales": total_sucursales,
        "total_proveedores": total_proveedores,
        "total_categorias": total_categorias,
        "stock_total": stock_total
    }
    
@router.get("/parche-db")
def arreglar_descripcion_prendas():
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE prendas ALTER COLUMN descripcion TYPE TEXT;"))
        return {"mensaje": "¡Columna descripción ampliada con éxito! Ya puedes guardar textos largos."}
    except Exception as e:
        return {"error": str(e)}
    
@router.post("/checkout/presencial")
def registrar_venta_presencial(venta: VentaPresencialCreate, db: Session = Depends(get_db)):
    try:
        # 1. Crear la Orden (Ticket)
        nueva_orden = Orden(
            nombre_cliente="Cliente Presencial", 
            correo_cliente="N/A",
            telefono_cliente="N/A",
            direccion_envio="Venta en Tienda Física",
            total=venta.total,
            estado="COMPLETADO" 
            # ELIMINAMOS metodo_pago, tipo_venta y sucursal_id porque no existen en la tabla Orden
        )
        
        db.add(nueva_orden)
        db.flush() # Obtenemos el ID de la orden sin hacer commit todavía

        # 2. Registrar el detalle y descontar el stock
        for item in venta.items:
            # Guardamos la línea de la factura
            nuevo_detalle = DetalleOrden(
                orden_id=nueva_orden.id,
                prenda_id=item.prenda_id,
                variante_id=item.variante_id,
                cantidad=item.cantidad,
                precio_unitario=item.precio
            )
            db.add(nuevo_detalle)

            # Buscamos el stock exacto en LA SUCURSAL DEL CAJERO
            inventario = db.query(Inventario).filter(
                Inventario.sucursal_id == venta.sucursal_id,
                Inventario.variante_id == item.variante_id
            ).first()

            # Validación de seguridad por si intentan vender algo agotado
            if not inventario or inventario.stock_disponible < item.cantidad:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Stock insuficiente para la variante {item.variante_id} en esta sucursal."
                )
            
            # Descontamos el stock
            inventario.stock_disponible -= item.cantidad

        # Si todo sale bien, guardamos definitivamente en la base de datos
        db.commit()
        db.refresh(nueva_orden)

        return {
            "mensaje": "Venta registrada e inventario actualizado",
            "orden_id": nueva_orden.id,
            "metodo_pago": venta.metodo_pago
        }

    except HTTPException as he:
        db.rollback()
        raise he
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")
    
@router.get("/inventario/sucursal/{sucursal_id}")
def obtener_inventario_sucursal(sucursal_id: int, db: Session = Depends(get_db)):
    # Hacemos un JOIN de las 3 tablas para armar el producto completo
    resultados = db.query(
        Inventario.stock_disponible,
        VariantePrenda.id.label("variante_id"),
        VariantePrenda.talla,
        VariantePrenda.color,
        Prenda.id.label("prenda_id"),
        Prenda.nombre,
        Prenda.precio_base
    ).join(
        VariantePrenda, Inventario.variante_id == VariantePrenda.id
    ).join(
        Prenda, VariantePrenda.prenda_id == Prenda.id
    ).filter(
        Inventario.sucursal_id == sucursal_id,
        Inventario.stock_disponible > 0  # Solo mostramos lo que se puede vender
    ).all()

    # Formateamos la respuesta para que encaje perfecto con el frontend
    productos = []
    for row in resultados:
        productos.append({
            "prenda_id": row.prenda_id,
            "variante_id": row.variante_id,
            "nombre": f"{row.nombre} ({row.color} - {row.talla})",
            "precio": row.precio_base,
            "stock": row.stock_disponible
        })
    
    return productos

@router.post("/sucursales-disponibles")
def obtener_sucursales_disponibles(items: List[ItemCarritoCheck], db: Session = Depends(get_db)):
    todas_sucursales = db.query(Sucursal).all()
    sucursales_validas = []

    for sucursal in todas_sucursales:
        disponible = True
        
        # Verificamos si esta sucursal tiene stock de TODO el carrito
        for item in items:
            inventario = db.query(Inventario).filter(
                Inventario.sucursal_id == sucursal.id,
                Inventario.variante_id == item.variante_id
            ).first()
            
            # Si no hay inventario o no alcanza, descartamos esta sucursal
            if not inventario or inventario.stock_disponible < item.cantidad:
                disponible = False
                break 
        
        # Si pasó la prueba de todos los items, la agregamos a la lista
        if disponible:
            sucursales_validas.append({
                "id": sucursal.id,
                "nombre": sucursal.nombre
            })
            
    return sucursales_validas

@router.get("/ordenes/historial")
def obtener_historial_ventas(db: Session = Depends(get_db)):
    # Traemos las órdenes ordenadas de la más reciente a la más antigua
    ordenes = db.query(Orden).order_by(Orden.id.desc()).all()
    return ordenes

@router.get("/agrupado/secciones")
def obtener_catalogo_por_secciones(db: Session = Depends(get_db)):
    categorias = db.query(Categoria).all()
    resultado = []
    
    for cat in categorias:
        prendas_data = []
        for prenda in cat.prendas:
            prendas_data.append({
                "prenda_id": prenda.id,
                "nombre": prenda.nombre,
                "precio": prenda.precio_base,
                "imagen_url": prenda.imagen_url,
                "variantes": [{"id": v.id, "talla": v.talla, "color": v.color} for v in prenda.variantes]
            })
        
        # Solo mandamos la sección si tiene prendas adentro
        if prendas_data:
            resultado.append({
                "id_seccion": cat.id,
                "nombre_seccion": cat.nombre, 
                "prendas": prendas_data
            })
            
    return resultado