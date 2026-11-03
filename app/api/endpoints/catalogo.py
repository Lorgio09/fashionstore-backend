import os
import base64
from typing import List, Optional

import cloudinary
import cloudinary.uploader
import requests
import stripe
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import func

from app.core.contexto import (
    ROLES_ADMIN,
    ROLES_GESTION,
    ROLES_PERSONAL,
    Contexto,
    ContextoPublico,
    get_contexto_publico,
    requiere_roles,
)
from app.core.security import registrar_bitacora
from app.models.inventario import Prenda, Categoria, Proveedor, Sucursal, Inventario, VariantePrenda, Temporada, Coleccion, Orden, DetalleOrden
from app.models.usuarios import ROL_ADMIN_EMPRESA, ROL_CLIENTE
from app.schemas.catalogo import PrendaResponse, CategoriaBase, CategoriaResponse, ProveedorResponse, VarianteStockCreate, TemporadaBase, TemporadaResponse, ColeccionBase, ColeccionResponse
from app.schemas.reservas import OrdenCreate
from app.services import suscripciones as svc_suscripciones
from app.services.validaciones import obtener_o_404, validar_variantes

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
router = APIRouter()

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

# Todas las consultas pasan por un contexto de empresa:
#  - Contexto (usuario autenticado): get_contexto / requiere_roles
#  - ContextoPublico (tienda): get_contexto_publico (token, header X-Empresa o empresa por defecto)
# El filtro por empresa lo aplica el ORM (app/db/tenant.py).


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


def _cliente_id(ctx: ContextoPublico) -> Optional[int]:
    if ctx.usuario is not None and ctx.usuario.rol.nombre == ROL_CLIENTE:
        return ctx.usuario.id
    return None


# ==========================================
# 2. RUTAS ESTÁTICAS
# ==========================================

# --- PRENDAS (Catálogo) ---
@router.get("/", response_model=List[PrendaResponse])
def obtener_catalogo(ctx: ContextoPublico = Depends(get_contexto_publico)):
    return ctx.db.query(Prenda).all()


@router.post("/", response_model=PrendaResponse)
def crear_prenda(
    nombre: str = Form(...),
    descripcion: str = Form(None),
    precio_base: float = Form(...),
    categoria_id: int = Form(...),
    proveedor_id: int = Form(...),
    imagen: UploadFile = File(...),
    ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION)),
):
    db = ctx.db
    obtener_o_404(db, Categoria, categoria_id, "Categoría")
    obtener_o_404(db, Proveedor, proveedor_id, "Proveedor")

    # Subimos a Cloudinary
    resultado_nube = cloudinary.uploader.upload(imagen.file, folder="fashionstore_prendas")
    url_imagen_db = resultado_nube.get("secure_url")

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
        registrar_bitacora(db, ctx.usuario.id, "INSERTAR", "prendas", nueva_prenda.id, f"Se creó la prenda: {nueva_prenda.nombre}")
        return nueva_prenda
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error al guardar: {str(e)}")


# --- SUCURSALES ---
@router.get("/sucursales")
def obtener_sucursales(ctx: ContextoPublico = Depends(get_contexto_publico)):
    # Solo las activas: son las que atienden reservas y ventas.
    return ctx.db.query(Sucursal).filter(Sucursal.activa.is_(True)).order_by(Sucursal.id).all()


@router.post("/sucursales")
def crear_sucursal(
    sucursal: SucursalCreate,
    ctx: Contexto = Depends(requiere_roles(*ROLES_ADMIN)),
):
    # RN06: límite de sucursales activas según el plan
    svc_suscripciones.verificar_cupo_sucursales(ctx.db, ctx.empresa_id)
    nueva_sucursal = Sucursal(nombre=sucursal.nombre, direccion=sucursal.direccion, activa=True)
    ctx.db.add(nueva_sucursal)
    ctx.db.commit()
    ctx.db.refresh(nueva_sucursal)

    registrar_bitacora(ctx.db, ctx.usuario.id, "INSERTAR", "sucursales", nueva_sucursal.id, f"Se creó la sucursal: {nueva_sucursal.nombre}")
    return nueva_sucursal


@router.post("/variantes-stock")
def registrar_variante_y_stock(
    datos: VarianteStockCreate,
    ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION)),
):
    db = ctx.db
    obtener_o_404(db, Prenda, datos.prenda_id, "Prenda")
    obtener_o_404(db, Sucursal, datos.sucursal_id, "Sucursal")
    if db.query(VariantePrenda).filter(VariantePrenda.codigo_sku == datos.codigo_sku).first():
        raise HTTPException(status_code=409, detail=f"El SKU {datos.codigo_sku} ya existe en la empresa")

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

    registrar_bitacora(db, ctx.usuario.id, "INSERTAR", "inventario", nuevo_inventario.id, f"Se agregó stock para SKU: {datos.codigo_sku}")
    return {"mensaje": "Variante y stock registrados correctamente", "sku": datos.codigo_sku}


# --- CATEGORÍAS ---
@router.get("/categorias", response_model=List[CategoriaResponse])
def obtener_categorias(ctx: ContextoPublico = Depends(get_contexto_publico)):
    return ctx.db.query(Categoria).all()


@router.post("/categorias", response_model=CategoriaResponse)
def crear_categoria(
    categoria: CategoriaBase,
    ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION)),
):
    nueva_categoria = Categoria(nombre=categoria.nombre)
    ctx.db.add(nueva_categoria)
    ctx.db.commit()
    ctx.db.refresh(nueva_categoria)

    registrar_bitacora(ctx.db, ctx.usuario.id, "INSERTAR", "categorias", nueva_categoria.id, f"Se creó la categoría: {nueva_categoria.nombre}")
    return nueva_categoria


# --- PROVEEDORES ---
@router.get("/proveedores", response_model=List[ProveedorResponse])
def obtener_proveedores(ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION))):
    return ctx.db.query(Proveedor).all()


@router.post("/proveedores")
def crear_proveedor(
    proveedor: ProveedorCreate,
    ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION)),
):
    nuevo_proveedor = Proveedor(razon_social=proveedor.nombre)
    ctx.db.add(nuevo_proveedor)
    ctx.db.commit()
    ctx.db.refresh(nuevo_proveedor)

    registrar_bitacora(ctx.db, ctx.usuario.id, "INSERTAR", "proveedores", nuevo_proveedor.id, f"Se registró el proveedor: {nuevo_proveedor.razon_social}")
    return nuevo_proveedor


# --- COLECCIONES ---
@router.get("/colecciones", response_model=List[ColeccionResponse])
def obtener_colecciones(ctx: ContextoPublico = Depends(get_contexto_publico)):
    return ctx.db.query(Coleccion).all()


@router.post("/colecciones", response_model=ColeccionResponse)
def crear_coleccion(
    coleccion: ColeccionBase,
    ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION)),
):
    nueva_coleccion = Coleccion(nombre=coleccion.nombre, descripcion=coleccion.descripcion)
    ctx.db.add(nueva_coleccion)
    ctx.db.commit()
    ctx.db.refresh(nueva_coleccion)

    registrar_bitacora(ctx.db, ctx.usuario.id, "INSERTAR", "colecciones", nueva_coleccion.id, f"Se creó la colección: {nueva_coleccion.nombre}")
    return nueva_coleccion


# --- TEMPORADAS ---
@router.get("/temporadas", response_model=List[TemporadaResponse])
def obtener_temporadas(ctx: ContextoPublico = Depends(get_contexto_publico)):
    return ctx.db.query(Temporada).all()


@router.post("/temporadas", response_model=TemporadaResponse)
def crear_temporada(
    temporada: TemporadaBase,
    ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION)),
):
    nueva_temporada = Temporada(
        nombre=temporada.nombre,
        fecha_inicio=temporada.fecha_inicio,
        fecha_fin=temporada.fecha_fin
    )
    ctx.db.add(nueva_temporada)
    ctx.db.commit()
    ctx.db.refresh(nueva_temporada)

    registrar_bitacora(ctx.db, ctx.usuario.id, "INSERTAR", "temporadas", nueva_temporada.id, f"Se creó la temporada: {nueva_temporada.nombre}")
    return nueva_temporada


@router.get("/{prenda_id}/variantes")
def obtener_variantes_prenda(prenda_id: int, ctx: ContextoPublico = Depends(get_contexto_publico)):
    db = ctx.db
    variantes = db.query(VariantePrenda).filter(VariantePrenda.prenda_id == prenda_id).all()

    resultado = []
    for v in variantes:
        # Sumamos el stock de esta variante en todas las sucursales de la empresa
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
    ctx: ContextoPublico = Depends(get_contexto_publico),
):
    db = ctx.db
    validar_variantes(db, [item.variante_id for item in orden_datos.items])

    # 1. Calcular total y guardar la orden como PENDIENTE
    total_calculado = sum(item.precio * item.cantidad for item in orden_datos.items)

    nueva_orden = Orden(
        nombre_cliente=orden_datos.nombre_cliente,
        correo_cliente=orden_datos.correo_cliente,
        telefono_cliente=orden_datos.telefono_cliente,
        direccion_envio=orden_datos.direccion_envio,
        total=total_calculado,
        estado="PENDIENTE",
        canal="WEB",
        metodo_pago="QR",
        cliente_id=_cliente_id(ctx),
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
def simular_pago_orden(orden_id: int, ctx: ContextoPublico = Depends(get_contexto_publico)):
    db = ctx.db
    orden = obtener_o_404(db, Orden, orden_id, "Orden")

    if orden.estado != "PENDIENTE":
        raise HTTPException(status_code=400, detail=f"La orden ya está en estado {orden.estado}")

    # 1. Descontamos el stock físico del inventario (con bloqueo de fila: RNF04)
    for detalle in orden.detalles:
        inventario = (
            db.query(Inventario)
            .filter(Inventario.variante_id == detalle.variante_id, Inventario.stock_disponible >= detalle.cantidad)
            .with_for_update()
            .first()
        )
        if inventario is None:
            db.rollback()
            raise HTTPException(status_code=400, detail="Stock insuficiente en el momento de pagar.")
        inventario.stock_disponible -= detalle.cantidad

    # 2. Marcamos la orden como pagada
    orden.estado = "PAGADO"
    db.commit()

    return {"mensaje": "Pago exitoso. Stock descontado y orden actualizada.", "estado": "PAGADO"}


@router.post("/checkout/{orden_id}/simular-rechazo")
def simular_rechazo_orden(orden_id: int, ctx: ContextoPublico = Depends(get_contexto_publico)):
    orden = obtener_o_404(ctx.db, Orden, orden_id, "Orden")
    if orden.estado != "PENDIENTE":
        raise HTTPException(status_code=400, detail=f"La orden ya está en estado {orden.estado}")

    orden.estado = "RECHAZADO"
    ctx.db.commit()

    return {"mensaje": "Pago rechazado. La orden fue cancelada.", "estado": "RECHAZADO"}


@router.post("/checkout/stripe")
def procesar_compra_stripe(
    orden_datos: OrdenCreate,
    ctx: ContextoPublico = Depends(get_contexto_publico),
):
    db = ctx.db
    validar_variantes(db, [item.variante_id for item in orden_datos.items])
    total_calculado = sum(item.precio * item.cantidad for item in orden_datos.items)

    # 1. Guardar la orden como PENDIENTE
    nueva_orden = Orden(
        nombre_cliente=orden_datos.nombre_cliente,
        correo_cliente=orden_datos.correo_cliente,
        telefono_cliente=orden_datos.telefono_cliente,
        direccion_envio=orden_datos.direccion_envio,
        total=total_calculado,
        estado="PENDIENTE",
        canal="WEB",
        metodo_pago="STRIPE",
        cliente_id=_cliente_id(ctx),
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
                    "currency": "bob",  # O "usd" si tu cuenta de Stripe no soporta bolivianos
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


@router.get("/dashboard/resumen")
def obtener_resumen_dashboard(ctx: Contexto = Depends(requiere_roles(*ROLES_PERSONAL))):
    db = ctx.db
    return {
        "total_prendas": db.query(Prenda).count(),
        "total_sucursales": db.query(Sucursal).filter(Sucursal.activa.is_(True)).count(),
        "total_proveedores": db.query(Proveedor).count(),
        "total_categorias": db.query(Categoria).count(),
        # Stock disponible en todas las sucursales de la empresa
        "stock_total": db.query(func.sum(Inventario.stock_disponible)).scalar() or 0,
    }


@router.post("/checkout/presencial")
def registrar_venta_presencial(
    venta: VentaPresencialCreate,
    ctx: Contexto = Depends(requiere_roles(*ROLES_PERSONAL)),
):
    db = ctx.db
    sucursal = obtener_o_404(db, Sucursal, venta.sucursal_id, "Sucursal")
    if not sucursal.activa:
        raise HTTPException(status_code=409, detail="La sucursal está inactiva")
    # El cajero/encargado solo vende en su propia sucursal; el administrador en cualquiera.
    if ctx.rol != ROL_ADMIN_EMPRESA and ctx.usuario.sucursal_id and ctx.usuario.sucursal_id != venta.sucursal_id:
        raise HTTPException(status_code=403, detail="Solo puede registrar ventas en su sucursal asignada")
    if any(item.cantidad <= 0 for item in venta.items):
        raise HTTPException(status_code=422, detail="Las cantidades deben ser mayores a cero")
    validar_variantes(db, [item.variante_id for item in venta.items])

    try:
        # 1. Crear la Orden (Ticket)
        nueva_orden = Orden(
            nombre_cliente="Cliente Presencial",
            correo_cliente="N/A",
            telefono_cliente="N/A",
            direccion_envio="Venta en Tienda Física",
            total=sum(item.precio * item.cantidad for item in venta.items),
            estado="COMPLETADO",
            canal="PRESENCIAL",
            metodo_pago=venta.metodo_pago.upper(),
            sucursal_id=venta.sucursal_id,
            usuario_id=ctx.usuario.id,
        )

        db.add(nueva_orden)
        db.flush()  # Obtenemos el ID de la orden sin hacer commit todavía

        # 2. Registrar el detalle y descontar el stock
        for item in venta.items:
            db.add(DetalleOrden(
                orden_id=nueva_orden.id,
                prenda_id=item.prenda_id,
                variante_id=item.variante_id,
                cantidad=item.cantidad,
                precio_unitario=item.precio
            ))

            # Stock exacto en LA SUCURSAL DEL CAJERO, con bloqueo de fila (RNF04)
            inventario = db.query(Inventario).filter(
                Inventario.sucursal_id == venta.sucursal_id,
                Inventario.variante_id == item.variante_id
            ).with_for_update().first()

            if not inventario or inventario.stock_disponible < item.cantidad:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stock insuficiente para la variante {item.variante_id} en esta sucursal."
                )
            inventario.stock_disponible -= item.cantidad

        db.commit()
        db.refresh(nueva_orden)

        return {
            "mensaje": "Venta registrada e inventario actualizado",
            "orden_id": nueva_orden.id,
            "metodo_pago": venta.metodo_pago
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


@router.get("/inventario/sucursal/{sucursal_id}")
def obtener_inventario_sucursal(sucursal_id: int, ctx: Contexto = Depends(requiere_roles(*ROLES_PERSONAL))):
    obtener_o_404(ctx.db, Sucursal, sucursal_id, "Sucursal")
    resultados = ctx.db.query(
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

    return [
        {
            "prenda_id": row.prenda_id,
            "variante_id": row.variante_id,
            "nombre": f"{row.nombre} ({row.color} - {row.talla})",
            "precio": row.precio_base,
            "stock": row.stock_disponible
        }
        for row in resultados
    ]


@router.post("/sucursales-disponibles")
def obtener_sucursales_disponibles(items: List[ItemCarritoCheck], ctx: ContextoPublico = Depends(get_contexto_publico)):
    db = ctx.db
    sucursales_validas = []
    for sucursal in db.query(Sucursal).filter(Sucursal.activa.is_(True)).all():
        disponible = True
        # Verificamos si esta sucursal tiene stock de TODO el carrito
        for item in items:
            inventario = db.query(Inventario).filter(
                Inventario.sucursal_id == sucursal.id,
                Inventario.variante_id == item.variante_id
            ).first()
            if not inventario or inventario.stock_disponible < item.cantidad:
                disponible = False
                break
        if disponible:
            sucursales_validas.append({"id": sucursal.id, "nombre": sucursal.nombre})

    return sucursales_validas


@router.get("/ordenes/historial")
def obtener_historial_ventas(ctx: Contexto = Depends(requiere_roles(*ROLES_PERSONAL))):
    # De la más reciente a la más antigua
    return ctx.db.query(Orden).order_by(Orden.id.desc()).all()


@router.get("/agrupado/secciones")
def obtener_catalogo_por_secciones(ctx: ContextoPublico = Depends(get_contexto_publico)):
    resultado = []
    for cat in ctx.db.query(Categoria).all():
        prendas_data = [
            {
                "prenda_id": prenda.id,
                "nombre": prenda.nombre,
                "precio": prenda.precio_base,
                "imagen_url": prenda.imagen_url,
                "variantes": [{"id": v.id, "talla": v.talla, "color": v.color} for v in prenda.variantes]
            }
            for prenda in cat.prendas
        ]
        # Solo mandamos la sección si tiene prendas adentro
        if prendas_data:
            resultado.append({
                "id_seccion": cat.id,
                "nombre_seccion": cat.nombre,
                "prendas": prendas_data
            })
    return resultado


# ==========================================
# 3. RUTAS DINÁMICAS (al final para no capturar las estáticas)
# ==========================================
@router.get("/{prenda_id}", response_model=PrendaResponse)
def obtener_prenda(prenda_id: int, ctx: ContextoPublico = Depends(get_contexto_publico)):
    return obtener_o_404(ctx.db, Prenda, prenda_id, "Prenda")


@router.put("/{prenda_id}", response_model=PrendaResponse)
def actualizar_prenda(
    prenda_id: int,
    nombre: str = Form(None),
    descripcion: str = Form(None),
    precio_base: float = Form(None),
    categoria_id: int = Form(None),
    proveedor_id: int = Form(None),
    imagen: UploadFile = File(None),
    ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION)),
):
    db = ctx.db
    prenda = obtener_o_404(db, Prenda, prenda_id, "Prenda")

    if nombre: prenda.nombre = nombre
    if descripcion: prenda.descripcion = descripcion
    if precio_base: prenda.precio_base = precio_base
    if categoria_id:
        obtener_o_404(db, Categoria, categoria_id, "Categoría")
        prenda.categoria_id = categoria_id
    if proveedor_id:
        obtener_o_404(db, Proveedor, proveedor_id, "Proveedor")
        prenda.proveedor_id = proveedor_id

    # Si suben una imagen nueva, la mandamos a Cloudinary
    if imagen:
        resultado_nube = cloudinary.uploader.upload(imagen.file, folder="fashionstore_prendas")
        prenda.imagen_url = resultado_nube.get("secure_url")

    db.commit()
    db.refresh(prenda)

    registrar_bitacora(db, ctx.usuario.id, "MODIFICAR", "prendas", prenda.id, f"Se editó la prenda con ID: {prenda.id}")
    return prenda


@router.delete("/{prenda_id}")
def eliminar_prenda(prenda_id: int, ctx: Contexto = Depends(requiere_roles(*ROLES_GESTION))):
    prenda = obtener_o_404(ctx.db, Prenda, prenda_id, "Prenda")
    ctx.db.delete(prenda)
    ctx.db.commit()

    registrar_bitacora(ctx.db, ctx.usuario.id, "ELIMINAR", "prendas", prenda_id, f"Se eliminó la prenda con ID: {prenda_id}")
    return {"mensaje": "Prenda eliminada con éxito"}
