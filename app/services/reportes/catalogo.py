"""
Catálogo cerrado de reportes y validación de la intención (examen 8.3 y 8.4).

La IA solo propone una ``Intencion``. Antes de consultar nada, el backend comprueba que el tipo de
reporte esté en este catálogo, que los filtros sean válidos y que las sucursales, categorías y
productos pertenezcan a la empresa del usuario. Además, el Encargado solo ve su sucursal.
"""
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from app.core.contexto import Contexto
from app.models.inventario import Categoria, Prenda, Sucursal
from app.models.usuarios import ROL_ENCARGADO
from app.schemas.reportes import Intencion

# Bolivia no tiene horario de verano: UTC-4 todo el año. Las fechas se guardan en UTC.
OFFSET_HORAS = int(os.getenv("REPORTES_OFFSET_HORAS", "-4"))
RANGO_MAXIMO_DIAS = 366 * 3  # RNF09: evita consultas desproporcionadas
LIMITE_POR_DEFECTO = 10


class ReporteInvalido(Exception):
    """La intención no se puede ejecutar; el mensaje se muestra al usuario."""

    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


@dataclass(frozen=True)
class TipoReporte:
    codigo: str
    nombre: str
    descripcion: str
    usa_fechas: bool
    filtros: tuple            # filtros opcionales que acepta además de las sucursales
    grafico: str
    ejemplos: tuple
    usa_sucursales: bool = True
    futuro: bool = False      # las fechas son un horizonte de predicción (desde mañana)


TIPOS = {
    t.codigo: t
    for t in (
        TipoReporte(
            "ventas_por_periodo", "Ventas por período",
            "Cantidad de ventas, unidades, monto y ticket promedio por día, semana o mes.",
            True, ("categorias", "productos", "canal", "agrupacion"), "lineas",
            ("Generá un gráfico de ventas por semana", "Ventas diarias de octubre"),
        ),
        TipoReporte(
            "ventas_por_sucursal", "Ventas por sucursal",
            "Ventas y monto de cada sucursal; con agrupación compara las sucursales mes a mes o semana a semana.",
            True, ("categorias", "productos", "canal", "agrupacion"), "barras",
            ("Mostrame las ventas de septiembre agrupadas por sucursal",
             "Compará las ventas de las sucursales durante los últimos tres meses"),
        ),
        TipoReporte(
            "productos_mas_vendidos", "Productos más vendidos",
            "Ranking de productos por unidades vendidas y monto.",
            True, ("categorias", "canal", "limite"), "barras",
            ("¿Cuáles fueron los diez productos más vendidos este mes?",),
        ),
        TipoReporte(
            "ingresos_por_categoria", "Ingresos por categoría",
            "Monto vendido y participación de cada categoría.",
            True, ("productos", "canal"), "torta",
            ("¿Qué categorías generaron mayores ingresos durante este período?",),
        ),
        TipoReporte(
            "stock_bajo", "Productos con menor existencia",
            "Variantes (talla y color) con menos stock disponible, por sucursal. Es el stock actual.",
            False, ("categorias", "productos", "limite"), "barras",
            ("Mostrame los productos con menor existencia",),
        ),
        TipoReporte(
            "devoluciones_por_motivo", "Devoluciones por motivo",
            "Solicitudes de devolución o cambio agrupadas por motivo: cantidad, unidades, valor y estado.",
            True, (), "barras",
            ("¿Por qué motivos nos devuelven más prendas?",),
        ),
        # ----- Reportes inteligentes del módulo de Machine Learning (examen 8.5) -----
        TipoReporte(
            "prediccion_demanda", "Predicción de demanda",
            "Unidades que se espera vender por sucursal y categoría en los próximos días (modelo supervisado), "
            "con rango probable, stock actual, días de cobertura y alerta de quiebre de stock.",
            True, ("categorias",), "barras",
            ("¿Cuánto voy a vender la próxima semana?", "¿Qué categorías se van a quedar sin stock?"),
            futuro=True,
        ),
        TipoReporte(
            "segmentos_clientes", "Segmentos de clientes",
            "Grupos de clientes descubiertos por el modelo no supervisado (recencia, frecuencia, monto), "
            "con su perfil y una acción sugerida.",
            False, (), "torta",
            ("Mostrame los segmentos de clientes",), usa_sucursales=False,
        ),
        TipoReporte(
            "evaluacion_modelos", "Evaluación de los modelos de ML",
            "Métricas de evaluación y validación de los modelos de predicción y segmentación.",
            False, (), "tabla",
            ("¿Qué tan precisos son los modelos?",), usa_sucursales=False,
        ),
    )
}
HORIZONTE_MAXIMO_DIAS = 28

NOMBRES_FILTRO = {"categorias": "categoría", "productos": "producto", "canal": "canal",
                  "agrupacion": "agrupación", "limite": "cantidad de resultados"}


def ejemplos() -> list[str]:
    return [e for t in TIPOS.values() for e in t.ejemplos]


def hoy_local() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=OFFSET_HORAS)).date()


def inicio_utc(dia: date) -> datetime:
    """Medianoche local de ``dia`` expresada en UTC sin zona (como se guardan las fechas)."""
    return datetime.combine(dia, time.min) - timedelta(hours=OFFSET_HORAS)


def fmt_fecha(d: date) -> str:
    return d.strftime("%d/%m/%Y")


@dataclass
class Validada:
    """Intención lista para ejecutar, con los nombres de los filtros para mostrarlos."""
    intencion: Intencion
    tipo: TipoReporte
    supuestos: list = field(default_factory=list)
    sucursales: dict = field(default_factory=dict)   # id -> nombre
    categorias: dict = field(default_factory=dict)
    productos: dict = field(default_factory=dict)


def _nombres(ctx: Contexto, modelo, columna, ids: list[int], etiqueta: str) -> dict:
    if not ids:
        return {}
    filas = (
        ctx.db.query(modelo.id, columna)
        .filter(modelo.empresa_id == ctx.empresa_id, modelo.id.in_(ids))  # además del filtro automático
        .all()
    )
    encontrados = {i: n for i, n in filas}
    faltan = sorted(set(ids) - encontrados.keys())
    if faltan:
        raise ReporteInvalido(f"{etiqueta} no encontrada(s) en su empresa: {faltan}")
    return encontrados


def _periodo_por_defecto(it: Intencion, hoy: date) -> tuple[date, date, str]:
    if it.agrupacion == "semana":
        lunes = hoy - timedelta(days=hoy.weekday())
        return lunes - timedelta(weeks=7), hoy, "las últimas 8 semanas"
    if it.agrupacion == "mes":
        mes = hoy.month - 5
        anio = hoy.year + (mes - 1) // 12
        return date(anio, (mes - 1) % 12 + 1, 1), hoy, "los últimos 6 meses"
    return hoy.replace(day=1), hoy, "el mes actual"


def validar(ctx: Contexto, intencion: Intencion) -> Validada:
    tipo = TIPOS.get(intencion.tipo)
    if tipo is None:
        disponibles = ", ".join(t.nombre for t in TIPOS.values())
        raise ReporteInvalido(f"Ese tipo de reporte no está disponible. Puedo generar: {disponibles}.")

    it = intencion.model_copy(deep=True)
    supuestos: list[str] = []

    if not tipo.usa_sucursales and it.sucursal_ids:
        supuestos.append("Este reporte es de toda la empresa: el filtro de sucursal no aplica.")
        it.sucursal_ids = []
    # Alcance del usuario autenticado (8.4): el Encargado solo consulta su sucursal.
    if tipo.usa_sucursales and ctx.rol == ROL_ENCARGADO and ctx.usuario.sucursal_id:
        if it.sucursal_ids and it.sucursal_ids != [ctx.usuario.sucursal_id]:
            supuestos.append("Como Encargado de sucursal, el reporte se limita a su sucursal.")
        it.sucursal_ids = [ctx.usuario.sucursal_id]

    # Filtros que este reporte no usa: se ignoran y se avisa.
    for filtro, atributo, vacio in (("categorias", "categoria_ids", []), ("productos", "prenda_ids", []),
                                    ("canal", "canal", None), ("agrupacion", "agrupacion", None),
                                    ("limite", "limite", None)):
        if getattr(it, atributo) and filtro not in tipo.filtros:
            supuestos.append(f"El filtro de {NOMBRES_FILTRO[filtro]} no aplica a este reporte y se ignoró.")
            setattr(it, atributo, vacio)

    hoy = hoy_local()
    if tipo.futuro:
        manana = hoy + timedelta(days=1)
        if it.fecha_desde is None and it.fecha_hasta is None:
            it.fecha_desde, it.fecha_hasta = manana, hoy + timedelta(days=7)
            supuestos.append("No se indicó un período: se predicen los próximos 7 días.")
        if it.fecha_desde is None or it.fecha_desde < manana:
            if it.fecha_desde is not None:
                supuestos.append("Una predicción empieza desde mañana: se ajustó la fecha inicial.")
            it.fecha_desde = manana
        if it.fecha_hasta is None or it.fecha_hasta < it.fecha_desde:
            it.fecha_hasta = it.fecha_desde + timedelta(days=6)
        if it.fecha_hasta > hoy + timedelta(days=HORIZONTE_MAXIMO_DIAS):
            it.fecha_hasta = hoy + timedelta(days=HORIZONTE_MAXIMO_DIAS)
            supuestos.append(f"El modelo predice como máximo {HORIZONTE_MAXIMO_DIAS} días hacia adelante.")
    elif tipo.usa_fechas:
        if it.fecha_desde is None and it.fecha_hasta is None:
            it.fecha_desde, it.fecha_hasta, descripcion = _periodo_por_defecto(it, hoy)
            supuestos.append(f"No se indicó un período: se usó {descripcion}.")
        elif it.fecha_desde is None:
            it.fecha_desde = it.fecha_hasta.replace(day=1)
            supuestos.append("No se indicó la fecha inicial: se usó el inicio de ese mes.")
        elif it.fecha_hasta is None:
            it.fecha_hasta = max(hoy, it.fecha_desde)
        if it.fecha_desde > it.fecha_hasta:
            raise ReporteInvalido("La fecha inicial es posterior a la fecha final.")
        if (it.fecha_hasta - it.fecha_desde).days > RANGO_MAXIMO_DIAS:
            raise ReporteInvalido("El período máximo de un reporte es de 3 años.")
        if tipo.codigo == "ventas_por_periodo" and it.agrupacion is None:
            dias = (it.fecha_hasta - it.fecha_desde).days + 1
            it.agrupacion = "dia" if dias <= 31 else "semana" if dias <= 120 else "mes"
    elif it.fecha_desde or it.fecha_hasta:
        supuestos.append("Este reporte muestra el stock actual: el período indicado no aplica." if tipo.codigo == "stock_bajo"
                         else "Este reporte no usa un período: las fechas indicadas no aplican.")
        it.fecha_desde = it.fecha_hasta = None

    if "limite" in tipo.filtros and it.limite is None:
        it.limite = LIMITE_POR_DEFECTO
    it.grafico = it.grafico or tipo.grafico

    return Validada(
        intencion=it, tipo=tipo, supuestos=supuestos,
        sucursales=_nombres(ctx, Sucursal, Sucursal.nombre, it.sucursal_ids, "Sucursal"),
        categorias=_nombres(ctx, Categoria, Categoria.nombre, it.categoria_ids, "Categoría"),
        productos=_nombres(ctx, Prenda, Prenda.nombre, it.prenda_ids, "Producto"),
    )
