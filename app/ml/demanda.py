"""
Aprendizaje SUPERVISADO: predicción de la demanda diaria (unidades) por sucursal y categoría.
Examen 8.4: selección de variables y preprocesamiento (2), entrenamiento (3), evaluación y validación (5).

- Variable objetivo: unidades vendidas en un día por una serie (sucursal o web, categoría).
- Variables: día de la semana, fin de semana, fin de mes, mes (temporada), promedio de los últimos 7 y
  28 días de la serie, y la serie codificada (one-hot de sucursal y categoría).
- Algoritmo: Gradient Boosting (HistGradientBoostingRegressor) con pérdida Poisson, la adecuada para
  conteos (unidades por día: enteros pequeños, nunca negativos, con varianza que crece con la media).
- Selección de variables: se compararon configuraciones con la misma validación y se descartaron las
  que agregaban ruido (ver VARIABLES_DESCARTADAS). Resultado documentado en el reporte de evaluación.
- Validación temporal (nunca se entrena con el futuro):
    * prueba final: las últimas 4 semanas, pronosticadas de forma recursiva como en producción;
    * validación cruzada temporal de 3 bloques de 14 días dentro del período de entrenamiento;
    * comparación contra un método simple (promedio del mismo día de la semana de las 4 semanas previas).
- Rango probable: percentiles 10 y 90 de una distribución de Poisson con la media predicha.
- Importancia de variables: por permutación sobre los datos de prueba (cuánto empeora el error si se
  desordena esa variable).
"""
import time
from datetime import date, timedelta

import numpy as np
from scipy.stats import poisson
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from app.ml.datos import DatosInsuficientes, HistoriaDemanda

ALGORITMO = "HistGradientBoostingRegressor (pérdida Poisson)"
PARAMETROS = dict(loss="poisson", max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=20,
                  random_state=41)
VENTANA = 28            # días de historia que necesita cada fila (promedio de 28 días)
HORIZONTE_PRUEBA = 28   # últimas 4 semanas reservadas para la prueba final
PLIEGUES_CV, HORIZONTE_CV = 3, 14
MIN_DIAS = VENTANA + 28 + HORIZONTE_PRUEBA      # 84 días
MIN_DIAS_CV = MIN_DIAS + PLIEGUES_CV * HORIZONTE_CV
MIN_VENTAS = 200
REPETICIONES_PERMUTACION = 5

VARIABLES = ["dia_semana", "fin_de_semana", "fin_de_mes", "mes", "media_7", "media_28"]
ETIQUETAS = {
    "dia_semana": "Día de la semana", "fin_de_semana": "Fin de semana", "fin_de_mes": "Fin de mes",
    "mes": "Mes (temporada)", "media_7": "Promedio de los últimos 7 días",
    "media_28": "Promedio de los últimos 28 días", "sucursal": "Sucursal / canal", "categoria": "Categoría",
}
VARIABLES_DESCARTADAS = [
    {"variable": "Día del mes", "motivo": "No tiene un patrón real (solo el fin de mes): el modelo memorizaba ruido."},
    {"variable": "Ventas de hace 7 días", "motivo": "Un solo día es muy ruidoso; el promedio de 7 días lo reemplaza."},
    {"variable": "Tendencia (días transcurridos)", "motivo": "Los árboles no extrapolan fuera del rango de "
                                                             "entrenamiento; el nivel reciente ya lo capturan los promedios."},
]


# ---------------------------------------------------------------- variables
def nuevo_codificador(series: list, inicio: date) -> dict:
    sucursales = sorted({s for s, _ in series}, key=lambda x: (x is None, x or 0))
    categorias = sorted({c for _, c in series})
    return {"inicio": inicio, "sucursales": sucursales, "categorias": categorias,
            "columnas": VARIABLES + [f"sucursal:{s}" for s in sucursales] + [f"categoria:{c}" for c in categorias]}


def variables(cod: dict, serie: tuple, d: date, valores: dict) -> list:
    """Vector de variables de la serie en el día ``d`` usando SOLO valores anteriores a ``d``."""
    previos = [valores.get(d - timedelta(days=k), 0.0) for k in range(1, VENTANA + 1)]
    fila = [d.weekday(), 1 if d.weekday() >= 5 else 0, 1 if d.day >= 25 or d.day <= 2 else 0, d.month,
            sum(previos[:7]) / 7, sum(previos) / VENTANA]
    sucursal, categoria = serie
    fila += [1 if s == sucursal else 0 for s in cod["sucursales"]]
    fila += [1 if c == categoria else 0 for c in cod["categorias"]]
    return fila


def _conjunto(cod: dict, historia: HistoriaDemanda, series: list, desde: date, hasta: date):
    X, y = [], []
    for serie in series:
        valores = historia.series[serie]
        d = desde
        while d <= hasta:
            X.append(variables(cod, serie, d, valores))
            y.append(valores[d])
            d += timedelta(days=1)
    return np.array(X, dtype=float), np.array(y, dtype=float)


def _ajustar(X, y) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(**PARAMETROS).fit(X, y)


# ---------------------------------------------------------------- pronóstico
def pronosticar(modelo, cod: dict, historia: dict, series: list, inicio: date, fin: date) -> dict:
    """Pronóstico recursivo día a día desde ``inicio`` hasta ``fin``: cada predicción alimenta los promedios
    de los días siguientes. Devuelve {serie: {fecha: unidades esperadas}}."""
    valores = {s: {d: float(v) for d, v in historia.get(s, {}).items()} for s in series}
    salida = {s: {} for s in series}
    d = inicio
    while d <= fin and series:
        X = np.array([variables(cod, s, d, valores[s]) for s in series], dtype=float)
        media = np.clip(modelo.predict(X), 0, None)
        for i, s in enumerate(series):
            valores[s][d] = salida[s][d] = float(media[i])
        d += timedelta(days=1)
    return salida


def rango(media: float) -> tuple[float, float]:
    """Rango probable (80 %) de la cantidad vendida si la media esperada es ``media`` (Poisson)."""
    if media <= 0:
        return 0.0, 0.0
    return float(poisson.ppf(0.10, media)), float(poisson.ppf(0.90, media))


# ---------------------------------------------------------------- evaluación
def _promedio_mismo_dia(valores: dict, origen: date, d: date) -> float:
    """Método simple de referencia: promedio del mismo día de la semana en las 4 semanas previas al origen."""
    previos = [valores.get(origen - timedelta(days=k), 0) for k in range(0, VENTANA)
               if (origen - timedelta(days=k)).weekday() == d.weekday()]
    return sum(previos) / len(previos) if previos else 0.0


def _evaluar(cod: dict, historia: HistoriaDemanda, series: list, origen: date, horizonte: int):
    """Entrena con los días hasta ``origen`` y pronostica los ``horizonte`` días siguientes."""
    X, y = _conjunto(cod, historia, series, historia.desde + timedelta(days=VENTANA), origen)
    modelo = _ajustar(X, y)
    pasado = {s: {d: v for d, v in historia.series[s].items() if d <= origen} for s in series}
    pred = pronosticar(modelo, cod, pasado, series, origen + timedelta(days=1), origen + timedelta(days=horizonte))
    reales, predichos, base = [], [], []
    for s in series:
        for d, media in pred[s].items():
            reales.append(historia.series[s][d])
            predichos.append(media)
            base.append(_promedio_mismo_dia(historia.series[s], origen, d))
    return modelo, {"reales": np.array(reales), "predichos": np.array(predichos), "base": np.array(base)}


def _metricas(r: dict) -> dict:
    reales, pred, base = r["reales"], r["predichos"], r["base"]
    mae, mae_base = mean_absolute_error(reales, pred), mean_absolute_error(reales, base)
    total_real = float(reales.sum())
    return {
        "mae": round(float(mae), 3),
        "rmse": round(float(np.sqrt(mean_squared_error(reales, pred))), 3),
        "r2": round(float(r2_score(reales, pred)), 3),
        "mae_metodo_simple": round(float(mae_base), 3),
        "mejora_vs_simple_pct": round(100 * (mae_base - mae) / mae_base, 1) if mae_base else 0.0,
        "error_total_pct": round(100 * abs(float(pred.sum()) - total_real) / total_real, 1) if total_real else 0.0,
        "unidades_reales": int(total_real),
        "unidades_predichas": int(round(float(pred.sum()))),
    }


def importancias(modelo, cod: dict, X: np.ndarray, y: np.ndarray) -> list[dict]:
    """Importancia por permutación agrupada: las columnas one-hot de sucursal y de categoría se desordenan
    juntas. Se informa el aumento del error (MAE) como porcentaje del total de aumentos."""
    grupos: dict = {}
    for i, columna in enumerate(cod["columnas"]):
        grupos.setdefault(columna.split(":")[0], []).append(i)
    rng = np.random.default_rng(41)
    base = mean_absolute_error(y, modelo.predict(X))
    aumentos = {}
    for nombre, columnas in grupos.items():
        deltas = []
        for _ in range(REPETICIONES_PERMUTACION):
            Xp = X.copy()
            orden = rng.permutation(len(X))
            Xp[:, columnas] = X[orden][:, columnas]
            deltas.append(mean_absolute_error(y, modelo.predict(Xp)) - base)
        aumentos[nombre] = max(0.0, float(np.mean(deltas)))
    total = sum(aumentos.values()) or 1.0
    return sorted(({"variable": ETIQUETAS[k], "importancia": round(v / total, 4), "aumento_mae": round(v, 4)}
                   for k, v in aumentos.items()), key=lambda x: x["importancia"], reverse=True)


# ---------------------------------------------------------------- entrenamiento
def entrenar(historia: HistoriaDemanda) -> tuple[dict, dict, dict, dict]:
    """Devuelve (artefacto, métricas, parámetros, datos de entrenamiento)."""
    dias = (historia.hasta - historia.desde).days + 1
    if dias < MIN_DIAS or historia.ventas < MIN_VENTAS:
        raise DatosInsuficientes(
            f"Para predecir la demanda se necesitan al menos {MIN_DIAS} días de historia y {MIN_VENTAS} ventas; "
            f"la empresa tiene {dias} días y {historia.ventas} ventas.")
    inicio_reloj = time.monotonic()
    series = sorted(historia.series, key=lambda s: (s[0] is None, s[0] or 0, s[1]))
    cod = nuevo_codificador(series, historia.desde)
    primer_dia = historia.desde + timedelta(days=VENTANA)

    # 1. Prueba final: las últimas 4 semanas, pronosticadas como se hará en producción
    origen_prueba = historia.hasta - timedelta(days=HORIZONTE_PRUEBA)
    modelo_prueba, resultado_prueba = _evaluar(cod, historia, series, origen_prueba, HORIZONTE_PRUEBA)
    prueba = _metricas(resultado_prueba)
    X_prueba, y_prueba = _conjunto(cod, historia, series, origen_prueba + timedelta(days=1), historia.hasta)

    # 2. Validación cruzada temporal dentro del período de entrenamiento
    cv = []
    if dias >= MIN_DIAS_CV:
        for k in range(PLIEGUES_CV, 0, -1):
            origen = origen_prueba - timedelta(days=k * HORIZONTE_CV)
            m = _metricas(_evaluar(cod, historia, series, origen, HORIZONTE_CV)[1])
            cv.append({"origen": origen.isoformat(), "mae": m["mae"], "mae_metodo_simple": m["mae_metodo_simple"],
                       "mejora_vs_simple_pct": m["mejora_vs_simple_pct"]})

    # 3. Modelo final con todos los datos
    X, y = _conjunto(cod, historia, series, primer_dia, historia.hasta)
    modelo = _ajustar(X, y)

    maes = [f["mae"] for f in cv]
    metricas = {
        "prueba": prueba,
        "validacion_cruzada": {
            "pliegues": cv,
            "mae_promedio": round(float(np.mean(maes)), 3) if maes else None,
            "mae_desvio": round(float(np.std(maes)), 3) if maes else None,
            "mejora_promedio_pct": round(float(np.mean([f["mejora_vs_simple_pct"] for f in cv])), 1) if cv else None,
        },
        "importancias": importancias(modelo_prueba, cod, X_prueba, y_prueba),
    }
    artefacto = {"modelo": modelo, "codificador": cod, "series": series,
                 "sucursales": {s: historia.sucursales.get(s, "?") for s in cod["sucursales"]},
                 "categorias": {c: historia.categorias.get(c, "?") for c in cod["categorias"]}}
    parametros = {**{k: v for k, v in PARAMETROS.items()},
                  "variables": [ETIQUETAS[v] for v in VARIABLES] + ["Sucursal / canal", "Categoría"],
                  "variables_descartadas": VARIABLES_DESCARTADAS,
                  "horizonte_prueba_dias": HORIZONTE_PRUEBA, "pliegues_cv": PLIEGUES_CV, "horizonte_cv_dias": HORIZONTE_CV}
    datos = {"desde": historia.desde.isoformat(), "hasta": historia.hasta.isoformat(), "dias": dias,
             "ventas": historia.ventas, "series": len(series), "filas_entrenamiento": int(len(y)),
             "segundos": round(time.monotonic() - inicio_reloj, 1)}
    return artefacto, metricas, parametros, datos
