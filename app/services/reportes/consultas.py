"""
Consultas controladas de cada tipo de reporte (examen 8.1 y 8.3).

Cada consulta está escrita en el backend, recibe solo parámetros ya validados y filtra por la
empresa del usuario de forma explícita, además del filtro automático del ORM (RN03).
Las agregaciones se hacen en la base de datos agrupando por día; solo el paso de día a semana o mes
se hace en Python, sobre como máximo un registro por día (RNF09).
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Interval, func, literal_column

from app.core.contexto import Contexto
from app.models.inventario import Categoria, DetalleOrden, Inventario, Orden, Prenda, Sucursal, VariantePrenda
from app.services.reportes.catalogo import OFFSET_HORAS, Validada, fmt_fecha, inicio_utc

VENTAS_VALIDAS = ("PAGADO", "COMPLETADO")   # no cuentan las órdenes pendientes de pago ni las rechazadas
SIN_SUCURSAL = "Tienda en línea"
SIN_CATEGORIA = "Sin categoría"
CANALES = {"WEB": "Tienda en línea", "PRESENCIAL": "Presencial", "OFFLINE": "Offline"}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

MONTO = func.sum(DetalleOrden.cantidad * DetalleOrden.precio_unitario)
UNIDADES = func.sum(DetalleOrden.cantidad)
VENTAS = func.count(func.distinct(Orden.id))


# ---------------------------------------------------------------- utilidades
def _col(clave, titulo, tipo="texto"):
    return {"clave": clave, "titulo": titulo, "tipo": tipo}   # tipo: texto | entero | moneda | porcentaje


def _dinero(valor) -> float:
    return round(float(valor or 0), 2)


def _dia_local(db, columna):
    """Fecha local (no UTC) de la venta, calculada en la base de datos."""
    if db.get_bind().dialect.name == "sqlite":
        return func.date(columna, f"{OFFSET_HORAS:+d} hours")
    return func.date(columna + literal_column(f"INTERVAL '{OFFSET_HORAS} hours'", type_=Interval))


def _a_fecha(valor) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def _inicio_periodo(dia: date, agrupacion: str) -> date:
    if agrupacion == "semana":
        return dia - timedelta(days=dia.weekday())
    if agrupacion == "mes":
        return dia.replace(day=1)
    return dia


def _periodos(desde: date, hasta: date, agrupacion: str) -> list[date]:
    """Todos los períodos del rango, también los que no tuvieron ventas (para que el gráfico sea continuo)."""
    actual, salida = _inicio_periodo(desde, agrupacion), []
    while actual <= hasta:
        salida.append(actual)
        if agrupacion == "mes":
            actual = date(actual.year + actual.month // 12, actual.month % 12 + 1, 1)
        else:
            actual += timedelta(days=7 if agrupacion == "semana" else 1)
    return salida


def _etiqueta_periodo(inicio: date, agrupacion: str) -> str:
    if agrupacion == "mes":
        return f"{MESES[inicio.month - 1]} {inicio.year}"
    if agrupacion == "semana":
        return f"Semana del {inicio.strftime('%d/%m')}"
    return inicio.strftime("%d/%m/%Y")


def _ventas(ctx: Contexto, v: Validada, *columnas):
    """Detalles de venta válidos de la empresa con todos los filtros de la intención."""
    it = v.intencion
    q = (
        ctx.db.query(*columnas)
        .select_from(DetalleOrden)
        .join(Orden, DetalleOrden.orden_id == Orden.id)
        .join(Prenda, DetalleOrden.prenda_id == Prenda.id)
        .filter(
            Orden.empresa_id == ctx.empresa_id,
            Orden.estado.in_(VENTAS_VALIDAS),
            Orden.fecha_orden >= inicio_utc(it.fecha_desde),
            Orden.fecha_orden < inicio_utc(it.fecha_hasta + timedelta(days=1)),
        )
    )
    if it.sucursal_ids:
        q = q.filter(Orden.sucursal_id.in_(it.sucursal_ids))
    if it.canal:
        q = q.filter(Orden.canal == it.canal)
    if it.categoria_ids:
        q = q.filter(Prenda.categoria_id.in_(it.categoria_ids))
    if it.prenda_ids:
        q = q.filter(DetalleOrden.prenda_id.in_(it.prenda_ids))
    return q


def _nombres_sucursales(ctx: Contexto) -> dict:
    return {i: n for i, n in ctx.db.query(Sucursal.id, Sucursal.nombre).filter(Sucursal.empresa_id == ctx.empresa_id)}


def _participacion(filas: list[dict], total: float) -> None:
    for f in filas:
        f["participacion"] = round(100 * f["monto"] / total, 1) if total else 0.0


# ---------------------------------------------------------------- reportes
def ventas_por_periodo(ctx: Contexto, v: Validada) -> dict:
    it = v.intencion
    dia = _dia_local(ctx.db, Orden.fecha_orden).label("dia")
    por_periodo = defaultdict(lambda: {"ventas": 0, "unidades": 0, "monto": 0.0})
    for d, ventas, unidades, monto in _ventas(ctx, v, dia, VENTAS, UNIDADES, MONTO).group_by(dia).all():
        p = por_periodo[_inicio_periodo(_a_fecha(d), it.agrupacion)]
        p["ventas"] += ventas
        p["unidades"] += int(unidades or 0)
        p["monto"] += float(monto or 0)

    filas = []
    for inicio in _periodos(it.fecha_desde, it.fecha_hasta, it.agrupacion):
        p = por_periodo.get(inicio, {"ventas": 0, "unidades": 0, "monto": 0.0})
        filas.append({
            "periodo": _etiqueta_periodo(inicio, it.agrupacion), "desde": inicio.isoformat(),
            "ventas": p["ventas"], "unidades": p["unidades"], "monto": _dinero(p["monto"]),
            "ticket_promedio": _dinero(p["monto"] / p["ventas"]) if p["ventas"] else 0.0,
        })
    total_ventas = sum(f["ventas"] for f in filas)
    total_monto = _dinero(sum(f["monto"] for f in filas))
    return {
        "columnas": [_col("periodo", "Período"), _col("ventas", "Ventas", "entero"),
                     _col("unidades", "Unidades", "entero"), _col("monto", "Monto (Bs)", "moneda"),
                     _col("ticket_promedio", "Ticket promedio (Bs)", "moneda")],
        "filas": filas,
        "totales": {"periodo": "Total", "ventas": total_ventas, "unidades": sum(f["unidades"] for f in filas),
                    "monto": total_monto,
                    "ticket_promedio": _dinero(total_monto / total_ventas) if total_ventas else 0.0},
        "grafico": {"eje_x": "periodo", "series": [{"clave": "monto", "titulo": "Monto (Bs)"}]},
    }


def ventas_por_sucursal(ctx: Contexto, v: Validada) -> dict:
    it = v.intencion
    nombres = _nombres_sucursales(ctx)
    nombre = lambda sid: nombres.get(sid, SIN_SUCURSAL) if sid else SIN_SUCURSAL  # noqa: E731

    if not it.agrupacion:
        filas = [
            {"sucursal": nombre(sid), "ventas": ventas, "unidades": int(unidades or 0), "monto": _dinero(monto)}
            for sid, ventas, unidades, monto in _ventas(ctx, v, Orden.sucursal_id, VENTAS, UNIDADES, MONTO)
            .group_by(Orden.sucursal_id).all()
        ]
        filas.sort(key=lambda f: f["monto"], reverse=True)
        total = _dinero(sum(f["monto"] for f in filas))
        _participacion(filas, total)
        return {
            "columnas": [_col("sucursal", "Sucursal"), _col("ventas", "Ventas", "entero"),
                         _col("unidades", "Unidades", "entero"), _col("monto", "Monto (Bs)", "moneda"),
                         _col("participacion", "Participación (%)", "porcentaje")],
            "filas": filas,
            "totales": {"sucursal": "Total", "ventas": sum(f["ventas"] for f in filas),
                        "unidades": sum(f["unidades"] for f in filas), "monto": total, "participacion": 100.0 if total else 0.0},
            "grafico": {"eje_x": "sucursal", "series": [{"clave": "monto", "titulo": "Monto (Bs)"}]},
        }

    # Comparación en el tiempo: una columna por sucursal
    dia = _dia_local(ctx.db, Orden.fecha_orden).label("dia")
    datos = defaultdict(float)
    sucursales = set(it.sucursal_ids)
    for sid, d, monto in _ventas(ctx, v, Orden.sucursal_id, dia, MONTO).group_by(Orden.sucursal_id, dia).all():
        sucursales.add(sid)
        datos[(_inicio_periodo(_a_fecha(d), it.agrupacion), sid)] += float(monto or 0)
    orden = sorted(sucursales, key=lambda s: (s is None, nombre(s)))
    clave = lambda sid: f"s_{sid}" if sid else "s_web"  # noqa: E731

    filas = []
    for inicio in _periodos(it.fecha_desde, it.fecha_hasta, it.agrupacion):
        fila = {"periodo": _etiqueta_periodo(inicio, it.agrupacion), "desde": inicio.isoformat()}
        for sid in orden:
            fila[clave(sid)] = _dinero(datos.get((inicio, sid)))
        fila["total"] = _dinero(sum(fila[clave(s)] for s in orden))
        filas.append(fila)
    totales = {"periodo": "Total", **{clave(s): _dinero(sum(f[clave(s)] for f in filas)) for s in orden}}
    totales["total"] = _dinero(sum(f["total"] for f in filas))
    return {
        "columnas": [_col("periodo", "Período")]
        + [_col(clave(s), f"{nombre(s)} (Bs)", "moneda") for s in orden] + [_col("total", "Total (Bs)", "moneda")],
        "filas": filas,
        "totales": totales,
        "grafico": {"eje_x": "periodo", "series": [{"clave": clave(s), "titulo": nombre(s)} for s in orden]},
    }


def productos_mas_vendidos(ctx: Contexto, v: Validada) -> dict:
    unidades = UNIDADES.label("unidades")
    filas = (
        _ventas(ctx, v, Prenda.id, Prenda.nombre, Categoria.nombre, unidades, MONTO)
        .outerjoin(Categoria, Prenda.categoria_id == Categoria.id)
        .group_by(Prenda.id, Prenda.nombre, Categoria.nombre)
        .order_by(unidades.desc(), Prenda.nombre)
        .limit(v.intencion.limite).all()
    )
    filas = [
        {"posicion": i, "producto": nombre, "categoria": cat or SIN_CATEGORIA, "unidades": int(u or 0),
         "monto": _dinero(monto)}
        for i, (_id, nombre, cat, u, monto) in enumerate(filas, start=1)
    ]
    return {
        "columnas": [_col("posicion", "#", "entero"), _col("producto", "Producto"), _col("categoria", "Categoría"),
                     _col("unidades", "Unidades", "entero"), _col("monto", "Monto (Bs)", "moneda")],
        "filas": filas,
        "totales": {"producto": "Total", "unidades": sum(f["unidades"] for f in filas),
                    "monto": _dinero(sum(f["monto"] for f in filas))},
        "grafico": {"eje_x": "producto", "series": [{"clave": "unidades", "titulo": "Unidades vendidas"}]},
    }


def ingresos_por_categoria(ctx: Contexto, v: Validada) -> dict:
    monto = MONTO.label("monto")
    filas = [
        {"categoria": cat or SIN_CATEGORIA, "unidades": int(u or 0), "monto": _dinero(m)}
        for _id, cat, u, m in _ventas(ctx, v, Categoria.id, Categoria.nombre, UNIDADES, monto)
        .outerjoin(Categoria, Prenda.categoria_id == Categoria.id)
        .group_by(Categoria.id, Categoria.nombre).order_by(monto.desc()).all()
    ]
    total = _dinero(sum(f["monto"] for f in filas))
    _participacion(filas, total)
    return {
        "columnas": [_col("categoria", "Categoría"), _col("unidades", "Unidades", "entero"),
                     _col("monto", "Monto (Bs)", "moneda"), _col("participacion", "Participación (%)", "porcentaje")],
        "filas": filas,
        "totales": {"categoria": "Total", "unidades": sum(f["unidades"] for f in filas), "monto": total,
                    "participacion": 100.0 if total else 0.0},
        "grafico": {"eje_x": "categoria", "series": [{"clave": "monto", "titulo": "Monto (Bs)"}]},
    }


def stock_bajo(ctx: Contexto, v: Validada) -> dict:
    it = v.intencion
    q = (
        ctx.db.query(Prenda.nombre, VariantePrenda.talla, VariantePrenda.color, Sucursal.nombre,
                     Inventario.stock_disponible, Categoria.nombre)
        .select_from(Inventario)
        .join(VariantePrenda, Inventario.variante_id == VariantePrenda.id)
        .join(Prenda, VariantePrenda.prenda_id == Prenda.id)
        .join(Sucursal, Inventario.sucursal_id == Sucursal.id)
        .outerjoin(Categoria, Prenda.categoria_id == Categoria.id)
        .filter(Inventario.empresa_id == ctx.empresa_id, Sucursal.activa.is_(True))
    )
    if it.sucursal_ids:
        q = q.filter(Inventario.sucursal_id.in_(it.sucursal_ids))
    if it.categoria_ids:
        q = q.filter(Prenda.categoria_id.in_(it.categoria_ids))
    if it.prenda_ids:
        q = q.filter(Prenda.id.in_(it.prenda_ids))
    filas = [
        {"producto": p, "talla": t, "color": c, "sucursal": s, "categoria": cat or SIN_CATEGORIA,
         "stock": int(stock or 0), "etiqueta": f"{p} ({t}/{c}) - {s}"}
        for p, t, c, s, stock, cat in q.order_by(Inventario.stock_disponible.asc(), Prenda.nombre)
        .limit(it.limite).all()
    ]
    return {
        "columnas": [_col("producto", "Producto"), _col("talla", "Talla"), _col("color", "Color"),
                     _col("sucursal", "Sucursal"), _col("categoria", "Categoría"), _col("stock", "Stock", "entero")],
        "filas": filas,
        "totales": None,
        "grafico": {"eje_x": "etiqueta", "series": [{"clave": "stock", "titulo": "Stock disponible"}]},
    }


def _ml(nombre: str):
    """Los reportes del módulo de ML se importan al usarse (evita dependencias circulares y cargar scikit-learn)."""
    def ejecutor(ctx: Contexto, v: Validada) -> dict:
        from app.services.reportes import consultas_ml
        return getattr(consultas_ml, nombre)(ctx, v)
    return ejecutor


EJECUTORES = {
    "ventas_por_periodo": ventas_por_periodo,
    "ventas_por_sucursal": ventas_por_sucursal,
    "productos_mas_vendidos": productos_mas_vendidos,
    "ingresos_por_categoria": ingresos_por_categoria,
    "stock_bajo": stock_bajo,
    "prediccion_demanda": _ml("prediccion_demanda"),
    "segmentos_clientes": _ml("segmentos_clientes"),
    "evaluacion_modelos": _ml("evaluacion_modelos"),
}


def _filtros_legibles(v: Validada) -> list[dict]:
    it = v.intencion
    filtros = []
    if it.fecha_desde:
        filtros.append({"campo": "Período", "valor": f"{fmt_fecha(it.fecha_desde)} al {fmt_fecha(it.fecha_hasta)}"})
    if it.agrupacion:
        filtros.append({"campo": "Agrupación", "valor": {"dia": "Por día", "semana": "Por semana", "mes": "Por mes"}[it.agrupacion]})
    if v.tipo.usa_sucursales:
        filtros.append({"campo": "Sucursales", "valor": ", ".join(v.sucursales.values()) or "Todas"})
    if "categorias" in v.tipo.filtros:
        filtros.append({"campo": "Categorías", "valor": ", ".join(v.categorias.values()) or "Todas"})
    if "productos" in v.tipo.filtros:
        filtros.append({"campo": "Productos", "valor": ", ".join(v.productos.values()) or "Todos"})
    if "canal" in v.tipo.filtros:
        filtros.append({"campo": "Canal", "valor": CANALES.get(it.canal, "Todos")})
    if it.limite:
        filtros.append({"campo": "Resultados", "valor": f"Primeros {it.limite}"})
    return filtros


def ejecutar(ctx: Contexto, v: Validada) -> dict:
    datos = EJECUTORES[v.tipo.codigo](ctx, v)
    it = v.intencion
    subtitulo = datos.get("subtitulo") or (
        f"Del {fmt_fecha(it.fecha_desde)} al {fmt_fecha(it.fecha_hasta)}" if it.fecha_desde else "Stock actual")
    vacio = datos["vacio"] if "vacio" in datos else not any(
        f.get("ventas") or f.get("unidades") or f.get("total") or f.get("stock") is not None for f in datos["filas"])
    return {
        "tipo": v.tipo.codigo,
        "titulo": v.tipo.nombre,
        "subtitulo": subtitulo,
        "empresa": ctx.empresa.razon_social,
        "generado_por": ctx.usuario.nombre_completo,
        "generado_en": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "filtros": _filtros_legibles(v),
        "supuestos": [*v.supuestos, *datos.get("notas", [])],
        "columnas": datos["columnas"],
        "filas": datos["filas"],
        "totales": datos["totales"],
        "grafico": {"tipo": it.grafico if datos["grafico"]["series"] else "tabla", **datos["grafico"]},
        "vacio": vacio,
    }
