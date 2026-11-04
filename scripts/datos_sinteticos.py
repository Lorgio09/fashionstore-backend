"""
Datos sintéticos de la empresa demo "Estilo Urbano" (plan Profesional): catálogo, 3 sucursales,
clientes y ~6 meses de ventas con patrones realistas. Sirven para demostrar los reportes con IA
(examen 8.3) y como conjunto de entrenamiento del módulo de Machine Learning (examen 8.4).

Las ventas se guardan en las tablas reales (ordenes / detalles_orden): los reportes las consultan
en el momento, igual que a las ventas que se registren durante la demostración.

Patrones incluidos (para que el ML tenga algo que descubrir):
- Fines de semana y fin de mes venden más; la tendencia general crece ~1 % por semana.
- Temporada: chamarras suben en invierno (jun-ago); poleras y shorts en primavera/verano.
- Sucursales con distinto volumen (Equipetrol > Centro > Norte) y canal web en crecimiento.
- Tres perfiles de cliente (frecuente, premium, ocasional) con frecuencia y ticket distintos.

Generación determinista (semilla fija): siempre produce los mismos datos para la misma fecha.
"""
import random
from datetime import date, datetime, timedelta

from app.models.inventario import Categoria, DetalleOrden, Inventario, Orden, Prenda, Proveedor, Sucursal, VariantePrenda
from app.models.usuarios import ROL_CLIENTE, Rol, Usuario

SEMILLA = 41
DIAS_DE_HISTORIA = 183
OFFSET_HORAS = -4  # Bolivia

SUCURSALES = [
    # nombre, dirección, volumen base de ventas por día
    ("Estilo Urbano - Equipetrol", "Av. San Martín 450, Santa Cruz", 6.0),
    ("Estilo Urbano - Centro", "Calle Junín 210, Santa Cruz", 4.0),
    ("Estilo Urbano - Norte", "Av. Banzer 3er anillo, Santa Cruz", 2.5),
]

# categoria, prenda, precio, popularidad, tallas, colores
CATALOGO = [
    ("Poleras", "Polera Básica Algodón", 79.0, 10, ["S", "M", "L", "XL"], ["Blanco", "Negro", "Gris"]),
    ("Poleras", "Polera Oversize Urbana", 119.0, 7, ["M", "L", "XL"], ["Negro", "Beige"]),
    ("Poleras", "Polera Estampada Lomas", 99.0, 5, ["S", "M", "L"], ["Blanco", "Azul"]),
    ("Camisas", "Camisa Lino Oriente", 189.0, 4, ["M", "L"], ["Blanco", "Celeste"]),
    ("Camisas", "Camisa Cuadros Leñador", 159.0, 3, ["M", "L", "XL"], ["Rojo", "Verde"]),
    ("Pantalones", "Jean Slim Piraí", 249.0, 8, ["28", "30", "32", "34"], ["Azul", "Negro"]),
    ("Pantalones", "Jogger Cargo", 179.0, 6, ["S", "M", "L"], ["Verde", "Negro"]),
    ("Pantalones", "Short Denim Verano", 129.0, 4, ["28", "30", "32"], ["Azul"]),
    ("Chamarras", "Chamarra Puffer Andes", 459.0, 3, ["M", "L", "XL"], ["Negro", "Azul"]),
    ("Chamarras", "Chamarra Jean Clásica", 329.0, 3, ["S", "M", "L"], ["Azul"]),
    ("Accesorios", "Gorra Snapback", 69.0, 6, ["Única"], ["Negro", "Blanco"]),
    ("Accesorios", "Mochila Urbana", 219.0, 2, ["Única"], ["Negro", "Gris"]),
    ("Calzados", "Zapatilla Urbana Low", 389.0, 5, ["38", "40", "42"], ["Blanco", "Negro"]),
    ("Calzados", "Sandalia Playa", 99.0, 2, ["38", "40", "42"], ["Negro"]),
]

# Multiplicador por mes y categoría (temporada en el hemisferio sur)
TEMPORADA = {
    "Chamarras": {5: 1.8, 6: 2.6, 7: 2.8, 8: 1.9, 9: 1.1, 10: 0.6, 11: 0.4, 12: 0.4, 1: 0.3, 2: 0.3, 3: 0.6, 4: 1.1},
    "Poleras": {9: 1.2, 10: 1.4, 11: 1.5, 12: 1.6, 1: 1.5, 2: 1.3, 6: 0.8, 7: 0.7},
    "Calzados": {12: 1.5, 11: 1.2},
    "Pantalones": {8: 1.1, 9: 1.1},
}
FACTOR_DIA_SEMANA = [0.8, 0.85, 0.9, 1.0, 1.25, 1.6, 1.3]   # lunes..domingo
PERFILES = {
    # probabilidad de ser elegido en una venta identificada, unidades extra, sensibilidad a precio alto
    "frecuente": dict(cantidad=14, peso=3.0, extra=0.2, premium=0.3),
    "premium": dict(cantidad=8, peso=1.5, extra=0.5, premium=2.5),
    "ocasional": dict(cantidad=28, peso=0.4, extra=0.0, premium=0.6),
}
NOMBRES = ["Ana", "Luis", "María", "Jorge", "Carla", "Diego", "Valeria", "Marco", "Paola", "Andrés", "Lucía",
           "Fernando", "Daniela", "Sergio", "Gabriela", "Ricardo", "Camila", "Hugo", "Mariana", "Pablo"]
APELLIDOS = ["Rojas", "Vargas", "Gutiérrez", "Flores", "Mamani", "Suárez", "Justiniano", "Pérez", "Rivero",
             "Antelo", "Quiroga", "Saavedra", "Montaño", "Chávez", "Peña"]


def _utc(dia: date, hora: float) -> datetime:
    local = datetime.combine(dia, datetime.min.time()) + timedelta(hours=hora)
    return local - timedelta(hours=OFFSET_HORAS)


def crear_catalogo(db, empresa_id: str) -> tuple[list, list]:
    """Crea sucursales, categorías, prendas, variantes y stock. Devuelve (sucursales, prendas)."""
    rng = random.Random(SEMILLA)
    sucursales = []
    for nombre, direccion, _ in SUCURSALES:
        s = Sucursal(nombre=nombre, direccion=direccion, empresa_id=empresa_id)
        db.add(s)
        sucursales.append(s)
    proveedor = Proveedor(razon_social="Confecciones del Oriente", empresa_id=empresa_id)
    db.add(proveedor)
    db.flush()

    categorias, prendas = {}, []
    for cat, nombre, precio, popularidad, tallas, colores in CATALOGO:
        if cat not in categorias:
            categorias[cat] = Categoria(nombre=cat, empresa_id=empresa_id)
            db.add(categorias[cat])
            db.flush()
        p = Prenda(nombre=nombre, precio_base=precio, descripcion=f"{nombre} - colección Estilo Urbano",
                   categoria_id=categorias[cat].id, proveedor_id=proveedor.id, empresa_id=empresa_id)
        db.add(p)
        db.flush()
        variantes = []
        for talla in tallas:
            for color in colores:
                v = VariantePrenda(prenda_id=p.id, talla=talla, color=color, empresa_id=empresa_id,
                                   codigo_sku=f"EU-{p.id}-{talla}-{color[:3].upper()}")
                db.add(v)
                db.flush()
                variantes.append(v)
                for s in sucursales:
                    # Algunas variantes quedan con poco stock para el reporte de existencias
                    stock = rng.choice([0, 1, 2, 3]) if rng.random() < 0.15 else rng.randint(5, 30)
                    db.add(Inventario(variante_id=v.id, sucursal_id=s.id, stock_disponible=stock,
                                      stock_reservado=0, empresa_id=empresa_id))
        prendas.append({"prenda": p, "categoria": cat, "precio": precio, "popularidad": popularidad,
                        "variantes": variantes})
    return sucursales, prendas


def crear_clientes(db, empresa_id: str, password_hash: str) -> list[dict]:
    rng = random.Random(SEMILLA + 1)
    rol = db.query(Rol).filter(Rol.nombre == ROL_CLIENTE).one()
    clientes, n = [], 0
    for perfil, conf in PERFILES.items():
        for _ in range(conf["cantidad"]):
            n += 1
            nombre = f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}"
            u = Usuario(email=f"cliente{n:02d}@estilourbano.demo", nombre_completo=nombre, password_hash=password_hash,
                        telefono=f"7{rng.randint(1000000, 9999999)}", rol_id=rol.id, empresa_id=empresa_id)
            db.add(u)
            clientes.append({"usuario": u, "perfil": perfil, **conf})
    db.flush()
    return clientes


def generar_ventas(db, empresa_id: str, sucursales: list, prendas: list, clientes: list, personal: dict,
                   hasta: date) -> int:
    """Genera ventas diarias desde ``hasta - DIAS_DE_HISTORIA`` hasta ``hasta`` (inclusive)."""
    rng = random.Random(SEMILLA + 2)
    desde = hasta - timedelta(days=DIAS_DE_HISTORIA)
    pesos_clientes = [c["peso"] for c in clientes]
    total = 0
    dia = desde
    while dia <= hasta:
        semanas = (dia - desde).days / 7
        tendencia = 1 + 0.01 * semanas
        fin_de_mes = 1.2 if dia.day >= 25 or dia.day <= 2 else 1.0
        canales = [(s, base) for s, (_, _, base) in zip(sucursales, SUCURSALES)] + [(None, 1.5 + 0.03 * semanas)]
        for sucursal, base in canales:
            esperado = base * FACTOR_DIA_SEMANA[dia.weekday()] * tendencia * fin_de_mes
            for _ in range(max(0, round(rng.gauss(esperado, esperado ** 0.5)))):
                total += 1
                web = sucursal is None
                canal = "WEB" if web else ("OFFLINE" if rng.random() < 0.12 else "PRESENCIAL")
                cliente = None
                if web or rng.random() < 0.35:
                    cliente = rng.choices(clientes, weights=pesos_clientes)[0]

                pesos = []
                for p in prendas:
                    w = p["popularidad"] * TEMPORADA.get(p["categoria"], {}).get(dia.month, 1.0)
                    if cliente and p["precio"] > 250:
                        w *= cliente["premium"]
                    pesos.append(w)
                n_items = 1 + (rng.random() < 0.35) + (rng.random() < 0.1 + (cliente["extra"] if cliente else 0) * 0.3)
                elegidas = {id(p): p for p in rng.choices(prendas, weights=pesos, k=n_items)}.values()

                orden = Orden(
                    empresa_id=empresa_id, canal=canal, sucursal_id=sucursal.id if sucursal else None,
                    fecha_orden=_utc(dia, rng.uniform(9, 21.5)),
                    estado="PAGADO" if web else "COMPLETADO",
                    metodo_pago=rng.choice(["STRIPE", "QR"]) if web else (
                        "EFECTIVO" if canal == "OFFLINE" else rng.choices(["EFECTIVO", "QR", "TARJETA"], [6, 3, 1])[0]),
                    usuario_id=None if web else personal[sucursal.id],
                    cliente_id=cliente["usuario"].id if cliente else None,
                    nombre_cliente=cliente["usuario"].nombre_completo if cliente else "Cliente ocasional",
                    correo_cliente=cliente["usuario"].email if cliente else "N/A",
                    telefono_cliente=cliente["usuario"].telefono if cliente else "N/A",
                    direccion_envio="Envío a domicilio" if web else "Venta en tienda física",
                )
                monto = 0.0
                for p in elegidas:
                    cantidad = 1 + (rng.random() < 0.15)
                    precio = round(p["precio"] * (0.9 if rng.random() < 0.1 else 1.0), 2)  # 10 % con descuento
                    v = rng.choice(p["variantes"])
                    orden.detalles.append(DetalleOrden(prenda_id=p["prenda"].id, variante_id=v.id,
                                                       cantidad=cantidad, precio_unitario=precio))
                    monto += cantidad * precio
                orden.total = round(monto, 2)
                db.add(orden)
                # Algunas compras web quedan sin pagar: no deben contar en los reportes
                if web and rng.random() < 0.04:
                    orden.estado = rng.choice(["PENDIENTE", "RECHAZADO"])
        dia += timedelta(days=1)
        if dia.day == 1:
            db.flush()
    db.flush()
    return total
