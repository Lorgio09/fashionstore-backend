"""
Aprendizaje NO SUPERVISADO: segmentación de clientes (examen 8.4 y 8.5, "identificar grupos sin etiquetas").

- Variables (modelo RFM, estándar en comercio): Recencia (días desde la última compra), Frecuencia
  (compras), Monto (gasto total), más ticket promedio y % de unidades de productos caros.
  Se descartó el % de compras web: no diferencia a los clientes y bajaba la silueta (0,49 -> 0,41).
- Preprocesamiento: logaritmo en las variables muy sesgadas (recencia, frecuencia, monto, ticket) y
  estandarización (K-Means usa distancias: sin escalar, el monto dominaría a las demás).
- Algoritmo: K-Means. El número de grupos (k entre 2 y 6) se elige con el coeficiente de silueta.
- Validación: silueta, índice Davies-Bouldin y, con datos sintéticos, el índice Rand ajustado (ARI)
  contra los perfiles con los que se generaron los clientes.
"""
import math
import time
from typing import Optional

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, davies_bouldin_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from app.ml.datos import DatosInsuficientes

ALGORITMO = "KMeans"
K_MIN, K_MAX = 2, 6
MIN_CLIENTES = 10
SEMILLA = 41
DIAS_INACTIVO, DIAS_EN_RIESGO = 60, 30
VARIABLES_CLIENTE = ["recencia_dias", "frecuencia", "monto_total", "ticket_promedio", "pct_premium"]
VARIABLES_DESCARTADAS = [{"variable": "pct_web", "motivo": "No diferencia a los clientes (todos compran por web en proporción parecida): agregaba ruido y bajaba la silueta."}]
LOGARITMICAS = {"recencia_dias", "frecuencia", "monto_total", "ticket_promedio"}

PERFILES = {
    "Premium": ("Compran productos de mayor precio, con ticket alto.",
                "Ofrecer lanzamientos exclusivos y atención personalizada."),
    "Frecuentes": ("Compran muy seguido, con ticket moderado.",
                   "Programa de puntos o descuentos por fidelidad."),
    "Ocasionales": ("Compran pocas veces y con ticket bajo.",
                    "Promociones de entrada y recordatorios de temporada."),
    "En riesgo": (f"Compraban, pero llevan más de {DIAS_EN_RIESGO} días sin volver.",
                  "Recordatorio personalizado con las novedades de su categoría favorita."),
    "Inactivos": (f"Hace más de {DIAS_INACTIVO} días que no compran.",
                  "Campaña de reactivación con un cupón de descuento."),
}


def matriz(clientes: list[dict]) -> np.ndarray:
    return np.array([[math.log1p(c[v]) if v in LOGARITMICAS else c[v] for v in VARIABLES_CLIENTE]
                     for c in clientes], dtype=float)


def _nombrar(centros_z: np.ndarray, medias: list[dict]) -> dict[int, str]:
    """Nombre de cada grupo según su centro (z = desvíos respecto del promedio de clientes)."""
    i_rec, i_frec, i_ticket, i_prem = (VARIABLES_CLIENTE.index(v)
                                      for v in ("recencia_dias", "frecuencia", "ticket_promedio", "pct_premium"))
    nombres, usados = {}, {}
    for k, c in enumerate(centros_z):
        if medias[k]["recencia_dias"] > DIAS_INACTIVO:
            nombre = "Inactivos"
        elif medias[k]["recencia_dias"] > DIAS_EN_RIESGO:
            nombre = "En riesgo"
        elif c[i_frec] < -0.3:
            nombre = "Ocasionales"
        elif max(c[i_ticket], c[i_prem]) > c[i_frec]:
            nombre = "Premium"
        else:
            nombre = "Frecuentes"
        usados[nombre] = usados.get(nombre, 0) + 1
        nombres[k] = nombre if usados[nombre] == 1 else f"{nombre} ({usados[nombre]})"
    return nombres


def _medias(clientes: list[dict], etiquetas: np.ndarray, k: int) -> list[dict]:
    salida = []
    for g in range(k):
        grupo = [c for c, e in zip(clientes, etiquetas) if e == g]
        salida.append({v: round(sum(c[v] for c in grupo) / len(grupo), 3) if grupo else 0 for v in VARIABLES_CLIENTE})
    return salida


def entrenar(clientes: list[dict], verdad: Optional[dict] = None) -> tuple[dict, dict, dict, dict]:
    """Devuelve (artefacto, métricas, parámetros, datos). ``verdad``: {cliente_id: perfil} si se conoce."""
    if len(clientes) < MIN_CLIENTES:
        raise DatosInsuficientes(
            f"Para segmentar se necesitan al menos {MIN_CLIENTES} clientes con compras; la empresa tiene {len(clientes)}.")
    inicio = time.monotonic()
    escalador = StandardScaler().fit(matriz(clientes))
    Z = escalador.transform(matriz(clientes))

    curva = []
    for k in range(K_MIN, min(K_MAX, len(clientes) - 1) + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=SEMILLA).fit(Z)
        curva.append({"k": k, "silueta": round(float(silhouette_score(Z, km.labels_)), 4),
                      "inercia": round(float(km.inertia_), 2)})
    k = max(curva, key=lambda c: c["silueta"])["k"]
    modelo = KMeans(n_clusters=k, n_init=10, random_state=SEMILLA).fit(Z)
    etiquetas = modelo.labels_
    medias = _medias(clientes, etiquetas, k)
    nombres = _nombrar(modelo.cluster_centers_, medias)

    metricas = {
        "k": k,
        "silueta": round(float(silhouette_score(Z, etiquetas)), 4),
        "davies_bouldin": round(float(davies_bouldin_score(Z, etiquetas)), 4),
        "curva": curva,
        "segmentos": [{"segmento": nombres[g], "clientes": int((etiquetas == g).sum()), **medias[g]} for g in range(k)],
        "ari_perfiles_sinteticos": None,
    }
    if verdad:
        pares = [(verdad[c["cliente_id"]], e) for c, e in zip(clientes, etiquetas) if c["cliente_id"] in verdad]
        if len(pares) >= MIN_CLIENTES:
            metricas["ari_perfiles_sinteticos"] = round(float(adjusted_rand_score(*zip(*pares))), 4)

    artefacto = {"escalador": escalador, "modelo": modelo, "nombres": nombres}
    parametros = {"k_probados": f"{K_MIN} a {K_MAX}", "criterio": "coeficiente de silueta", "n_init": 10,
                  "variables": VARIABLES_CLIENTE, "variables_descartadas": VARIABLES_DESCARTADAS,
                  "transformacion": "log(1+x) en recencia, frecuencia, monto y ticket; "
                                                                   "estandarización z"}
    datos = {"clientes": len(clientes), "segundos": round(time.monotonic() - inicio, 1)}
    return artefacto, metricas, parametros, datos


def asignar(artefacto: dict, clientes: list[dict]) -> list[str]:
    if not clientes:
        return []
    etiquetas = artefacto["modelo"].predict(artefacto["escalador"].transform(matriz(clientes)))
    return [artefacto["nombres"][int(e)] for e in etiquetas]
