"""
Reportes inteligentes del módulo de ML (examen 8.5: "presentación de predicciones, patrones detectados y
métricas de evaluación"). Usan el mismo formato que los demás reportes, así que se piden en lenguaje
natural, se muestran en tabla y gráfico y se exportan a PDF/Excel igual que el resto.
"""
from datetime import datetime

from app.core.contexto import Contexto
from app.ml import servicio
from app.ml.datos import DatosInsuficientes
from app.models.ml import MODELO_DEMANDA, MODELO_SEGMENTACION
from app.services.reportes.catalogo import ReporteInvalido, Validada, fmt_fecha


def _col(clave, titulo, tipo="texto"):
    return {"clave": clave, "titulo": titulo, "tipo": tipo}


def _fecha(iso: str) -> str:
    return fmt_fecha(datetime.fromisoformat(iso.replace("Z", "")).date())


def _num(valor, decimales=2) -> str:
    return f"{valor:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _sin_prefijo_comun(nombres: list[str]) -> dict:
    """Quita el prefijo que comparten todas las sucursales ("Estilo Urbano - Centro" -> "Centro") para
    que las etiquetas del gráfico sean legibles."""
    validos = [n for n in nombres if " - " in n]
    if len(validos) < 2:
        return {n: n for n in nombres}
    prefijos = {n.rsplit(" - ", 1)[0] for n in validos}
    if len(prefijos) != 1:
        return {n: n for n in nombres}
    return {n: n.rsplit(" - ", 1)[1] if " - " in n else n for n in nombres}


def prediccion_demanda(ctx: Contexto, v: Validada) -> dict:
    it = v.intencion
    try:
        r = servicio.prediccion(ctx, it.fecha_desde, it.fecha_hasta, it.sucursal_ids or None, it.categoria_ids or None)
    except DatosInsuficientes as e:
        raise ReporteInvalido(e.mensaje)
    corto = _sin_prefijo_comun(sorted({f["sucursal"] for f in r["filas"]}))
    filas = []
    for f in r["filas"]:
        cobertura = f["cobertura_dias"] if f["cobertura_dias"] is not None and f["cobertura_dias"] < 365 else None
        filas.append({
            "sucursal": f["sucursal"], "categoria": f["categoria"], "etiqueta": f"{corto[f['sucursal']]} · {f['categoria']}",
            "unidades": round(f["unidades"]), "rango": f"{f['minimo']:.0f} a {f['maximo']:.0f}",
            "stock": f["stock"], "cobertura_dias": round(cobertura) if cobertura is not None else None,
            "alerta": f["alerta"],
        })
    return {
        "subtitulo": f"Predicción del {fmt_fecha(it.fecha_desde)} al {fmt_fecha(it.fecha_hasta)}",
        "columnas": [_col("sucursal", "Sucursal"), _col("categoria", "Categoría"),
                     _col("unidades", "Unidades estimadas", "entero"), _col("rango", "Rango probable"),
                     _col("stock", "Stock actual", "entero"), _col("cobertura_dias", "Cobertura (días)", "entero"),
                     _col("alerta", "Alerta")],
        "filas": filas,
        "totales": {"sucursal": "Total", "unidades": sum(f["unidades"] for f in filas),
                    "stock": sum(f["stock"] or 0 for f in filas)},
        "grafico": {"eje_x": "etiqueta", "series": [{"clave": "unidades", "titulo": "Unidades estimadas"}]},
        "notas": [f"Modelo de demanda versión {r['modelo']['version']} (Gradient Boosting, pérdida Poisson), entrenado "
                  f"el {_fecha(r['modelo']['entrenado_en'])}. Rango probable: 80 % de probabilidad (percentiles 10 y 90).",
                  "Alerta: CRÍTICO si el stock cubre menos de 7 días de demanda; ATENCIÓN si cubre menos de 14."],
        "vacio": not filas,
    }


def segmentos_clientes(ctx: Contexto, v: Validada) -> dict:
    try:
        r = servicio.segmentos(ctx, con_clientes=False)
    except DatosInsuficientes as e:
        raise ReporteInvalido(e.mensaje)
    met = r["modelo"]["metricas"]
    filas = [{k: s[k] for k in ("segmento", "clientes", "porcentaje", "recencia_dias", "frecuencia", "monto_total",
                                "ticket_promedio", "accion_sugerida")} for s in r["segmentos"]]
    return {
        "subtitulo": "Clientes con compras en los últimos 12 meses",
        "columnas": [_col("segmento", "Segmento"), _col("clientes", "Clientes", "entero"),
                     _col("porcentaje", "% de clientes", "porcentaje"), _col("recencia_dias", "Días desde la última compra", "entero"),
                     _col("frecuencia", "Compras promedio", "entero"), _col("monto_total", "Gasto promedio (Bs)", "moneda"),
                     _col("ticket_promedio", "Ticket promedio (Bs)", "moneda"), _col("accion_sugerida", "Acción sugerida")],
        "filas": filas,
        "totales": {"segmento": "Total", "clientes": sum(f["clientes"] for f in filas), "porcentaje": 100.0},
        "grafico": {"eje_x": "segmento", "series": [{"clave": "clientes", "titulo": "Clientes"}]},
        "notas": [f"Modelo K-Means versión {r['modelo']['version']}, entrenado el {_fecha(r['modelo']['entrenado_en'])}: "
                  f"{met['k']} segmentos elegidos por coeficiente de silueta ({_num(met['silueta'])})."],
        "vacio": not filas,
    }


def evaluacion_modelos(ctx: Contexto, v: Validada) -> dict:
    filas, notas = [], []
    for tipo in (MODELO_DEMANDA, MODELO_SEGMENTACION):
        try:
            registro, _ = servicio._modelo(ctx, tipo)
        except DatosInsuficientes as e:
            notas.append(e.mensaje)
            continue
        m = registro.metricas
        nombre = f"{'Demanda' if tipo == MODELO_DEMANDA else 'Segmentación'} v{registro.version}"
        if tipo == MODELO_DEMANDA:
            p, cv = m["prueba"], m["validacion_cruzada"]
            filas += [
                {"modelo": nombre, "metrica": "MAE (error absoluto medio)", "valor": f"{_num(p['mae'])} unid./día",
                 "interpretacion": "Cuánto se equivoca en promedio, por día y por sucursal-categoría."},
                {"modelo": nombre, "metrica": "RMSE", "valor": _num(p["rmse"]),
                 "interpretacion": "Como el MAE, pero castiga más los errores grandes."},
                {"modelo": nombre, "metrica": "R²", "valor": _num(p["r2"]),
                 "interpretacion": "Parte de la variación diaria que explica el modelo (1 = perfecta)."},
                {"modelo": nombre, "metrica": "Mejora frente al método simple", "valor": f"{_num(p['mejora_vs_simple_pct'], 1)} %",
                 "interpretacion": f"MAE del promedio del mismo día de la semana: {_num(p['mae_metodo_simple'])}."},
                {"modelo": nombre, "metrica": "Error en el total de 4 semanas", "valor": f"{_num(p['error_total_pct'], 1)} %",
                 "interpretacion": f"Predijo {p['unidades_predichas']} unidades; se vendieron {p['unidades_reales']}."},
            ]
            if cv["mae_promedio"] is not None:
                filas.append({"modelo": nombre, "metrica": "Validación cruzada temporal (MAE)",
                              "valor": f"{_num(cv['mae_promedio'])} ± {_num(cv['mae_desvio'])}",
                              "interpretacion": f"{len(cv['pliegues'])} bloques de 14 días: el error es estable en el tiempo."})
            principales = ", ".join(f"{i['variable']} ({_num(100 * i['importancia'], 0)} %)" for i in m["importancias"][:3])
            filas.append({"modelo": nombre, "metrica": "Variables más influyentes", "valor": principales,
                          "interpretacion": "Importancia por permutación: cuánto empeora el error si se desordena la variable."})
            descartadas = registro.parametros.get("variables_descartadas") or []
            if descartadas:
                filas.append({"modelo": nombre, "metrica": "Variables descartadas",
                              "valor": ", ".join(d["variable"] for d in descartadas),
                              "interpretacion": " ".join(d["motivo"] for d in descartadas)})
        else:
            filas += [
                {"modelo": nombre, "metrica": "Número de segmentos (k)", "valor": str(m["k"]),
                 "interpretacion": "Elegido automáticamente entre 2 y 6 con el coeficiente de silueta."},
                {"modelo": nombre, "metrica": "Coeficiente de silueta", "valor": _num(m["silueta"]),
                 "interpretacion": "De -1 a 1: cuanto más alto, mejor separados los grupos."},
                {"modelo": nombre, "metrica": "Índice Davies-Bouldin", "valor": _num(m["davies_bouldin"]),
                 "interpretacion": "Cuanto más bajo, más compactos y distintos los grupos."},
            ]
            if m.get("ari_perfiles_sinteticos") is not None:
                filas.append({"modelo": nombre, "metrica": "ARI frente a los perfiles sintéticos",
                              "valor": _num(m["ari_perfiles_sinteticos"]),
                              "interpretacion": "1 = recupera exactamente los perfiles con que se generaron los datos."})
    if not filas:
        raise ReporteInvalido(" ".join(notas) or "No hay modelos entrenados.")
    return {
        "subtitulo": "Validación con datos no vistos durante el entrenamiento",
        "columnas": [_col("modelo", "Modelo"), _col("metrica", "Métrica"), _col("valor", "Valor"),
                     _col("interpretacion", "Interpretación")],
        "filas": filas, "totales": None,
        "grafico": {"eje_x": "metrica", "series": []},
        "notas": notas, "vacio": False,
    }
