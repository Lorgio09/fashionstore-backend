"""
Servicio del módulo de analítica inteligente (examen 8.4 puntos 6 a 9 y 8.5).

Integra los modelos con el sistema: entrenamiento por empresa, predicción de demanda con cobertura de
stock, segmentación de clientes, métricas de evaluación y datos del dashboard analítico.
"""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import defer

from app.core.contexto import Contexto
from app.core.security import registrar_bitacora
from app.ml import almacen, datos, demanda, segmentacion
from app.ml.datos import WEB, DatosInsuficientes
from app.ml.datos_sinteticos import verdad_perfiles
from app.models.inventario import DetalleOrden, Inventario, Orden, Prenda, Sucursal, VariantePrenda
from app.models.ml import MODELO_DEMANDA, MODELO_SEGMENTACION, ModeloML
from app.services.reportes import catalogo
from app.services.reportes.catalogo import inicio_utc
from app.services.reportes.consultas import VENTAS_VALIDAS

DIAS_HISTORIA_PRONOSTICO = 40     # suficiente para las variables de 28 días + margen
DIAS_CRITICO, DIAS_ATENCION = 7, 14
CRITICO, ATENCION, OK, SIN_STOCK_PROPIO = "CRÍTICO", "ATENCIÓN", "OK", "—"


def _hoy() -> date:
    return catalogo.hoy_local()


# ---------------------------------------------------------------- entrenamiento
def entrenar(ctx: Contexto) -> dict:
    """Entrena ambos modelos con los datos de la empresa. Si uno no tiene datos suficientes, se informa
    y se entrena el otro; si ninguno puede entrenarse, lanza DatosInsuficientes."""
    db, eid = ctx.db, ctx.empresa_id
    hoy = _hoy()
    hasta = hoy - timedelta(days=1)   # solo días completos
    resultado, errores = {}, []

    primera = datos.primera_venta(db, eid)
    try:
        if primera is None:
            raise DatosInsuficientes("La empresa todavía no tiene ventas.")
        desde = max(hasta - timedelta(days=datos.DIAS_MAXIMOS_DE_HISTORIA - 1), primera)
        historia = datos.demanda_diaria(db, eid, hasta, desde=desde)
        art, met, par, dat = demanda.entrenar(historia)
        reg = almacen.guardar(db, eid, MODELO_DEMANDA, demanda.ALGORITMO, art, met, par, dat, ctx.usuario.id)
        resultado["demanda"] = _resumen(reg)
    except DatosInsuficientes as e:
        errores.append(e.mensaje)
        resultado["demanda"] = {"error": e.mensaje}

    try:
        clientes = datos.variables_clientes(db, eid, hoy)
        art, met, par, dat = segmentacion.entrenar(clientes, verdad_perfiles(clientes))
        reg = almacen.guardar(db, eid, MODELO_SEGMENTACION, segmentacion.ALGORITMO, art, met, par, dat, ctx.usuario.id)
        resultado["segmentacion"] = _resumen(reg)
    except DatosInsuficientes as e:
        errores.append(e.mensaje)
        resultado["segmentacion"] = {"error": e.mensaje}

    if len(errores) == 2:
        db.rollback()
        raise DatosInsuficientes(" ".join(errores))
    db.commit()
    registrar_bitacora(db, ctx.usuario.id, "ENTRENAR_MODELOS", "modelos_ml", 0,
                       "; ".join(f"{k}: v{v['version']}" for k, v in resultado.items() if "version" in v)
                       or "sin modelos")
    return resultado


def _resumen(reg: ModeloML) -> dict:
    return {"tipo": reg.tipo, "version": reg.version, "algoritmo": reg.algoritmo,
            "entrenado_en": reg.entrenado_en.isoformat() + "Z", "parametros": reg.parametros,
            "datos": reg.datos, "metricas": reg.metricas}


def modelos(ctx: Contexto) -> list[dict]:
    registros = (ctx.db.query(ModeloML).options(defer(ModeloML.artefacto))
                 .filter(ModeloML.empresa_id == ctx.empresa_id, ModeloML.activo.is_(True))
                 .order_by(ModeloML.tipo).all())
    return [_resumen(r) for r in registros]


def _modelo(ctx: Contexto, tipo: str) -> tuple[ModeloML, dict]:
    """Modelo activo de la empresa; si todavía no hay ninguno, se entrena en el momento."""
    registro = almacen.activo(ctx.db, ctx.empresa_id, tipo)
    if registro is None:
        resultado = entrenar(ctx)
        clave = "demanda" if tipo == MODELO_DEMANDA else "segmentacion"
        if "error" in resultado[clave]:
            raise DatosInsuficientes(resultado[clave]["error"])
        registro = almacen.activo(ctx.db, ctx.empresa_id, tipo)
    return registro, almacen.cargar(registro)


# ---------------------------------------------------------------- predicción de demanda
def _alerta(cobertura: Optional[float]) -> str:
    if cobertura is None:
        return SIN_STOCK_PROPIO
    return CRITICO if cobertura < DIAS_CRITICO else ATENCION if cobertura < DIAS_ATENCION else OK


def prediccion(ctx: Contexto, desde: date, hasta: date, sucursal_ids: Optional[list] = None,
               categoria_ids: Optional[list] = None) -> dict:
    registro, art = _modelo(ctx, MODELO_DEMANDA)
    hoy = _hoy()
    historia = datos.demanda_diaria(ctx.db, ctx.empresa_id, hoy - timedelta(days=1), dias=DIAS_HISTORIA_PRONOSTICO)
    series = [s for s in art["series"]
              if (not sucursal_ids or s[0] in sucursal_ids) and (not categoria_ids or s[1] in categoria_ids)]
    pred = demanda.pronosticar(art["modelo"], art["codificador"], historia.series, series, hoy, hasta)
    stock = datos.stock_por_serie(ctx.db, ctx.empresa_id)
    dias = (hasta - desde).days + 1

    filas = []
    for s in series:
        media = sum(v for d, v in pred[s].items() if desde <= d <= hasta)
        minimo, maximo = demanda.rango(media)
        en_stock = stock.get(s) if s[0] is not WEB else None
        diaria = media / dias if dias else 0
        cobertura = None if en_stock is None else (round(en_stock / diaria, 1) if diaria > 0 else 999.0)
        filas.append({
            "sucursal_id": s[0], "categoria_id": s[1],
            "sucursal": art["sucursales"].get(s[0], "?"), "categoria": art["categorias"].get(s[1], "?"),
            "unidades": round(media, 1), "minimo": minimo, "maximo": maximo, "promedio_diario": round(diaria, 2),
            "stock": en_stock, "cobertura_dias": cobertura, "alerta": _alerta(cobertura),
        })
    orden_alerta = {CRITICO: 0, ATENCION: 1, OK: 2, SIN_STOCK_PROPIO: 2}
    filas.sort(key=lambda f: (orden_alerta[f["alerta"]], -f["unidades"]))

    por_dia: dict = {}
    for s in series:
        for d, m in pred[s].items():
            por_dia[d] = por_dia.get(d, 0.0) + m
    return {
        "modelo": {"version": registro.version, "entrenado_en": registro.entrenado_en.isoformat() + "Z"},
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), "filas": filas,
        "diario": [{"fecha": d.isoformat(), "prediccion": round(m, 1), "minimo": demanda.rango(m)[0],
                    "maximo": demanda.rango(m)[1]} for d, m in sorted(por_dia.items()) if desde <= d <= hasta],
    }


def alertas_reposicion(ctx: Contexto, horizonte: int = DIAS_ATENCION, sucursal_ids: Optional[list] = None,
                       limite: int = 10) -> list[dict]:
    """Baja la predicción por categoría a cada variante (talla/color) según su participación en las ventas de
    los últimos 90 días, y la compara con su stock: las variantes que se agotarían primero."""
    hoy = _hoy()
    base = prediccion(ctx, hoy, hoy + timedelta(days=horizonte - 1), sucursal_ids)
    diaria_serie = {(f["sucursal_id"], f["categoria_id"]): f["promedio_diario"] for f in base["filas"]}
    ventas = (
        ctx.db.query(Orden.sucursal_id, Prenda.categoria_id, DetalleOrden.variante_id, func.sum(DetalleOrden.cantidad))
        .select_from(DetalleOrden).join(Orden, DetalleOrden.orden_id == Orden.id)
        .join(Prenda, DetalleOrden.prenda_id == Prenda.id)
        .filter(Orden.empresa_id == ctx.empresa_id, Orden.estado.in_(VENTAS_VALIDAS), Orden.sucursal_id.isnot(None),
                Orden.fecha_orden >= inicio_utc(hoy - timedelta(days=90)))
        .group_by(Orden.sucursal_id, Prenda.categoria_id, DetalleOrden.variante_id).all()
    )
    total_serie: dict = {}
    for s, c, _, u in ventas:
        total_serie[(s, c)] = total_serie.get((s, c), 0) + int(u or 0)
    demanda_variante = {(s, v): diaria_serie.get((s, c), 0) * int(u or 0) / total_serie[(s, c)]
                        for s, c, v, u in ventas if total_serie.get((s, c))}

    q = (ctx.db.query(Inventario.sucursal_id, Inventario.variante_id, Inventario.stock_disponible, Prenda.nombre,
                      VariantePrenda.talla, VariantePrenda.color, Sucursal.nombre)
         .join(VariantePrenda, Inventario.variante_id == VariantePrenda.id)
         .join(Prenda, VariantePrenda.prenda_id == Prenda.id)
         .join(Sucursal, Inventario.sucursal_id == Sucursal.id)
         .filter(Inventario.empresa_id == ctx.empresa_id, Sucursal.activa.is_(True)))
    if sucursal_ids:
        q = q.filter(Inventario.sucursal_id.in_(sucursal_ids))
    alertas = []
    for suc, var, stock, prenda, talla, color, nombre_suc in q.all():
        diaria = demanda_variante.get((suc, var), 0)
        if diaria <= 0:
            continue
        cobertura = round((stock or 0) / diaria, 1)
        if cobertura < horizonte:
            alertas.append({"producto": prenda, "talla": talla, "color": color, "sucursal": nombre_suc,
                            "stock": int(stock or 0), "demanda_diaria": round(diaria, 2), "cobertura_dias": cobertura,
                            "sugerido_reponer": max(0, round(diaria * 2 * horizonte - (stock or 0))),
                            "alerta": _alerta(cobertura)})
    alertas.sort(key=lambda a: a["cobertura_dias"])
    return alertas[:limite]


# ---------------------------------------------------------------- segmentación
def segmentos(ctx: Contexto, con_clientes: bool = True) -> dict:
    registro, art = _modelo(ctx, MODELO_SEGMENTACION)
    clientes = datos.variables_clientes(ctx.db, ctx.empresa_id, _hoy())
    for c, nombre in zip(clientes, segmentacion.asignar(art, clientes)):
        c["segmento"] = nombre
    resumen = []
    for nombre in sorted({c["segmento"] for c in clientes}):
        grupo = [c for c in clientes if c["segmento"] == nombre]
        perfil = segmentacion.PERFILES.get(nombre.split(" (")[0], ("", ""))
        resumen.append({
            "segmento": nombre, "clientes": len(grupo),
            "porcentaje": round(100 * len(grupo) / len(clientes), 1),
            "recencia_dias": round(sum(c["recencia_dias"] for c in grupo) / len(grupo), 1),
            "frecuencia": round(sum(c["frecuencia"] for c in grupo) / len(grupo), 1),
            "monto_total": round(sum(c["monto_total"] for c in grupo) / len(grupo), 2),
            "ticket_promedio": round(sum(c["ticket_promedio"] for c in grupo) / len(grupo), 2),
            "pct_premium": round(100 * sum(c["pct_premium"] for c in grupo) / len(grupo), 1),
            "descripcion": perfil[0], "accion_sugerida": perfil[1],
        })
    resumen.sort(key=lambda r: r["monto_total"], reverse=True)
    return {"modelo": {"version": registro.version, "entrenado_en": registro.entrenado_en.isoformat() + "Z",
                       "metricas": registro.metricas},
            "segmentos": resumen, "clientes": clientes if con_clientes else None}


# ---------------------------------------------------------------- dashboard analítico
def _ventas(ctx: Contexto, desde: date, hasta: date, sucursal_ids: Optional[list]) -> dict:
    q = (ctx.db.query(func.count(func.distinct(Orden.id)), func.sum(DetalleOrden.cantidad * DetalleOrden.precio_unitario),
                      func.sum(DetalleOrden.cantidad), func.count(func.distinct(Orden.cliente_id)))
         .select_from(DetalleOrden).join(Orden, DetalleOrden.orden_id == Orden.id)
         .filter(Orden.empresa_id == ctx.empresa_id, Orden.estado.in_(VENTAS_VALIDAS),
                 Orden.fecha_orden >= inicio_utc(desde), Orden.fecha_orden < inicio_utc(hasta + timedelta(days=1))))
    if sucursal_ids:
        q = q.filter(Orden.sucursal_id.in_(sucursal_ids))
    ventas, monto, unidades, clientes = q.one()
    return {"ventas": ventas or 0, "monto": round(float(monto or 0), 2), "unidades": int(unidades or 0),
            "clientes": clientes or 0}


def _indicador(actual: float, anterior: float) -> dict:
    variacion = round(100 * (actual - anterior) / anterior, 1) if anterior else None
    return {"valor": actual, "anterior": anterior, "variacion_pct": variacion}


def dashboard(ctx: Contexto, sucursal_ids: Optional[list] = None) -> dict:
    hoy = _hoy()
    inicio_mes = hoy.replace(day=1)
    corte = max(inicio_mes, hoy - timedelta(days=1))   # solo días completos (hoy todavía está en curso)
    fin_anterior = inicio_mes - timedelta(days=1)
    inicio_anterior = fin_anterior.replace(day=1)
    hasta_anterior = min(inicio_anterior + (corte - inicio_mes), fin_anterior)   # mismo avance del mes anterior
    mes = _ventas(ctx, inicio_mes, corte, sucursal_ids)
    previo = _ventas(ctx, inicio_anterior, hasta_anterior, sucursal_ids)
    ticket = lambda v: round(v["monto"] / v["ventas"], 2) if v["ventas"] else 0.0  # noqa: E731
    activos = _ventas(ctx, hoy - timedelta(days=29), hoy, sucursal_ids)["clientes"]
    activos_previos = _ventas(ctx, hoy - timedelta(days=59), hoy - timedelta(days=30), sucursal_ids)["clientes"]

    salida = {
        "generado_en": hoy.isoformat(),
        "indicadores": {
            "ventas_mes": _indicador(mes["monto"], previo["monto"]),
            "cantidad_ventas_mes": _indicador(mes["ventas"], previo["ventas"]),
            "ticket_promedio": _indicador(ticket(mes), ticket(previo)),
            "unidades_mes": _indicador(mes["unidades"], previo["unidades"]),
            "clientes_activos_30_dias": _indicador(activos, activos_previos),
        },
        "comparacion": f"{inicio_mes.strftime('%d/%m')}–{corte.strftime('%d/%m')} contra "
                       f"{inicio_anterior.strftime('%d/%m')}–{hasta_anterior.strftime('%d/%m')}",
        "serie": [], "segmentos": [], "alertas_reposicion": [], "modelos": {}, "avisos": [],
    }

    try:
        historia = datos.demanda_diaria(ctx.db, ctx.empresa_id, hoy - timedelta(days=1), dias=60)
        reales = {}
        for (suc, _), valores in historia.series.items():
            if sucursal_ids and suc not in sucursal_ids:
                continue
            for d, u in valores.items():
                reales[d] = reales.get(d, 0) + u
        pred = prediccion(ctx, hoy, hoy + timedelta(days=13), sucursal_ids)
        salida["serie"] = ([{"fecha": d.isoformat(), "real": reales.get(d, 0), "prediccion": None, "minimo": None,
                             "maximo": None} for d in historia.dias()]
                           + [{"fecha": p["fecha"], "real": None, "prediccion": p["prediccion"], "minimo": p["minimo"],
                               "maximo": p["maximo"]} for p in pred["diario"]])
        salida["alertas_reposicion"] = alertas_reposicion(ctx, sucursal_ids=sucursal_ids)
        registro = almacen.activo(ctx.db, ctx.empresa_id, MODELO_DEMANDA)
        salida["modelos"]["demanda"] = _resumen(registro)
    except DatosInsuficientes as e:
        salida["avisos"].append(e.mensaje)

    try:
        seg = segmentos(ctx, con_clientes=False)
        salida["segmentos"] = seg["segmentos"]
        registro = almacen.activo(ctx.db, ctx.empresa_id, MODELO_SEGMENTACION)
        salida["modelos"]["segmentacion"] = _resumen(registro)
    except DatosInsuficientes as e:
        salida["avisos"].append(e.mensaje)
    return salida
