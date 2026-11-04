"""
Exportación del reporte a PDF y Excel con formato de reporte convencional (examen 8.1):
encabezado con la empresa, título, filtros aplicados, gráfico, tabla con totales y análisis.

Colores: paleta categórica validada (orden fijo, nunca rotado; contraste compensado porque el gráfico
siempre va acompañado de su tabla). La misma paleta se publica en GET /ia/reportes/tipos para la web.
"""
from datetime import datetime, timedelta
from io import BytesIO
from xml.sax.saxutils import escape

from app.services.reportes.catalogo import OFFSET_HORAS

PALETA = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTROS = "#898781"          # porción "Otros" y textos secundarios
TINTA = "#0b0b0b"
TINTA_SECUNDARIA = "#52514e"
GRILLA = "#e4e3df"
MAX_CATEGORIAS_GRAFICO = 20
MAX_PORCIONES = 6


# ---------------------------------------------------------------- formato
def _fmt(valor, tipo: str) -> str:
    if valor is None or valor == "":
        return ""
    if tipo == "moneda":
        return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if tipo == "porcentaje":
        return f"{valor:.1f} %".replace(".", ",")
    if tipo == "entero":
        return f"{int(valor):,}".replace(",", ".")
    return str(valor)


def _fecha_local(iso: str) -> str:
    utc = datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=None)
    return (utc + timedelta(hours=OFFSET_HORAS)).strftime("%d/%m/%Y %H:%M")


def _corto(texto: str, n: int) -> str:
    texto = str(texto)
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def nombre_archivo(reporte: dict, formato: str) -> str:
    fecha = reporte["generado_en"][:10]
    return f"{reporte['tipo']}_{fecha}.{formato}"


def _datos_grafico(reporte: dict):
    """(etiquetas, series[(titulo, valores)]) limitado para que el gráfico sea legible."""
    g = reporte["grafico"]
    filas = reporte["filas"][:MAX_CATEGORIAS_GRAFICO]
    etiquetas = [str(f.get(g["eje_x"], "")) for f in filas]
    series = [(s["titulo"], [float(f.get(s["clave"]) or 0) for f in filas]) for s in g["series"]]
    return etiquetas, series


def _porciones(etiquetas, valores):
    pares = sorted(zip(etiquetas, valores), key=lambda p: p[1], reverse=True)
    pares = [p for p in pares if p[1] > 0]
    if len(pares) > MAX_PORCIONES:
        resto = sum(v for _, v in pares[MAX_PORCIONES - 1:])
        pares = pares[: MAX_PORCIONES - 1] + [("Otros", resto)]
    return pares


# ---------------------------------------------------------------- PDF
def _grafico_pdf(reporte: dict, ancho: float):
    from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
    from reportlab.graphics.charts.legends import Legend
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.widgets.markers import makeMarker
    from reportlab.lib import colors

    tipo = reporte["grafico"]["tipo"]
    if tipo == "tabla" or reporte["vacio"] or not reporte["filas"]:
        return None
    etiquetas, series = _datos_grafico(reporte)
    color = lambda i: colors.HexColor(PALETA[i % len(PALETA)])  # noqa: E731  (≤ 8 series: nunca se repite)
    gris, tinta = colors.HexColor(OTROS), colors.HexColor(TINTA_SECUNDARIA)

    if tipo == "torta":
        pares = _porciones(etiquetas, series[0][1])
        d = Drawing(ancho, 200)
        pie = Pie()
        pie.x, pie.y, pie.width, pie.height = 30, 15, 170, 170
        pie.data = [v for _, v in pares]
        pie.labels = None
        pie.slices.strokeColor, pie.slices.strokeWidth = colors.white, 2   # separación entre porciones
        for i, (nombre, _) in enumerate(pares):
            pie.slices[i].fillColor = gris if nombre == "Otros" else color(i)
        total = sum(v for _, v in pares) or 1
        leyenda = Legend()
        leyenda.x, leyenda.y, leyenda.alignment = 240, 170, "right"
        leyenda.fontSize, leyenda.fillColor = 8, tinta
        leyenda.colorNamePairs = [
            (gris if n == "Otros" else color(i), f"{_corto(n, 30)}  {100 * v / total:.1f} %".replace(".", ","))
            for i, (n, v) in enumerate(pares)
        ]
        d.add(pie)
        d.add(leyenda)
        return d

    horizontal = tipo == "barras" and (len(etiquetas) > 8 or max(len(e) for e in etiquetas) > 14)
    multiple = len(series) > 1
    if horizontal:
        alto = max(120, 16 * len(etiquetas) + 40)
        d = Drawing(ancho, alto)
        ch = HorizontalBarChart()
        ch.x, ch.y, ch.width, ch.height = 170, 20, ancho - 190, alto - 30
        ch.data = [tuple(reversed(v)) for _, v in series]
        ch.categoryAxis.categoryNames = [_corto(e, 34) for e in reversed(etiquetas)]
        ch.categoryAxis.labels.boxAnchor, ch.categoryAxis.labels.dx = "e", -4
    else:
        alto = 190 + (25 if multiple else 0)
        d = Drawing(ancho, alto)
        ch = HorizontalLineChart() if tipo == "lineas" else VerticalBarChart()
        ch.x, ch.y, ch.width, ch.height = 50, 55, ancho - 70, alto - 70 - (25 if multiple else 0)
        ch.data = [tuple(v) for _, v in series]
        ch.categoryAxis.categoryNames = [_corto(e, 16) for e in etiquetas]
        ch.categoryAxis.labels.angle, ch.categoryAxis.labels.boxAnchor = (30, "ne") if len(etiquetas) > 6 else (0, "n")

    for eje in (ch.categoryAxis, ch.valueAxis):
        eje.labels.fontSize, eje.labels.fillColor = 7, tinta
        eje.strokeColor = colors.HexColor(GRILLA)
    ch.valueAxis.valueMin = 0
    ch.valueAxis.visibleGrid, ch.valueAxis.gridStrokeColor = True, colors.HexColor(GRILLA)
    ch.valueAxis.labelTextFormat = lambda v: _fmt(v, "entero")

    for i in range(len(series)):
        if tipo == "lineas":
            ch.lines[i].strokeColor, ch.lines[i].strokeWidth = color(i), 2
            ch.lines[i].symbol = makeMarker("FilledCircle", size=4, fillColor=color(i), strokeColor=colors.white)
        else:
            ch.bars[i].fillColor, ch.bars[i].strokeColor, ch.bars[i].strokeWidth = color(i), colors.white, 1
    if tipo != "lineas":
        ch.barSpacing, ch.groupSpacing = 1, 6
    d.add(ch)

    if multiple:  # con 2 o más series, la leyenda siempre está presente
        leyenda = Legend()
        leyenda.x, leyenda.y, leyenda.alignment = 50, alto - 8, "right"
        # Ancho por elemento según el espacio disponible, para no cortar los nombres
        paso = min(190, (ancho - 60) / len(series))
        leyenda.columnMaximum, leyenda.deltax, leyenda.fontSize, leyenda.fillColor = 1, paso, 8, tinta
        leyenda.colorNamePairs = [(color(i), _corto(t, int(paso / 4.6))) for i, (t, _) in enumerate(series)]
        d.add(leyenda)
    return d


def a_pdf(reporte: dict, narrativa: str | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    columnas = reporte["columnas"]
    pagina = landscape(A4) if len(columnas) > 5 else A4
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=pagina, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=reporte["titulo"],
                            author=reporte["empresa"])
    estilos = getSampleStyleSheet()
    tinta, secundaria = colors.HexColor(TINTA), colors.HexColor(TINTA_SECUNDARIA)
    e_empresa = ParagraphStyle("empresa", parent=estilos["Normal"], fontSize=10, textColor=secundaria)
    e_titulo = ParagraphStyle("titulo", parent=estilos["Title"], alignment=0, fontSize=18, textColor=tinta, spaceAfter=2)
    e_normal = ParagraphStyle("normal", parent=estilos["Normal"], fontSize=9, textColor=tinta, leading=12)
    e_nota = ParagraphStyle("nota", parent=e_normal, textColor=secundaria, fontName="Helvetica-Oblique")
    e_seccion = ParagraphStyle("seccion", parent=estilos["Heading3"], textColor=tinta, spaceBefore=10, spaceAfter=4,
                               keepWithNext=1)  # el título nunca queda solo al pie de una página
    e_celda = ParagraphStyle("celda", parent=e_normal, fontSize=8, leading=10)

    elementos = [
        Paragraph(escape(reporte["empresa"]), e_empresa),
        Paragraph(escape(reporte["titulo"]), e_titulo),
        Paragraph(escape(reporte["subtitulo"]), e_normal),
        Paragraph(escape(f"Generado por {reporte['generado_por']} el {_fecha_local(reporte['generado_en'])}"), e_nota),
        Spacer(1, 8),
    ]
    filtros = Table([[f["campo"], f["valor"]] for f in reporte["filtros"]], hAlign="LEFT",
                    colWidths=[3.2 * cm, doc.width - 3.2 * cm])
    filtros.setStyle(TableStyle([
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8), ("FONT", (1, 0), (1, -1), "Helvetica", 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), tinta), ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    elementos.append(filtros)
    for s in reporte.get("supuestos") or []:
        elementos.append(Paragraph(escape(f"Nota: {s}"), e_nota))
    if narrativa:  # resumen ejecutivo arriba, antes del detalle
        elementos += [Paragraph("Resumen", e_seccion), Paragraph(escape(narrativa).replace("\n", "<br/>"), e_normal)]

    grafico = _grafico_pdf(reporte, doc.width)
    if grafico is not None:
        elementos += [Spacer(1, 10), grafico]

    elementos.append(Paragraph("Detalle", e_seccion))
    if reporte["vacio"]:
        elementos.append(Paragraph("No se encontraron datos para los filtros indicados.", e_normal))
    else:
        numericas = [c["tipo"] != "texto" for c in columnas]
        e_celda_num = ParagraphStyle("celda_num", parent=e_celda, alignment=2)
        cuerpo = [[Paragraph(f"<b>{escape(c['titulo'])}</b>", e_celda_num if n else e_celda)
                   for c, n in zip(columnas, numericas)]]
        for f in reporte["filas"]:
            cuerpo.append([_fmt(f.get(c["clave"]), c["tipo"]) if n else Paragraph(escape(str(f.get(c["clave"], ""))), e_celda)
                           for c, n in zip(columnas, numericas)])
        tiene_totales = bool(reporte["totales"])
        if tiene_totales:
            cuerpo.append([_fmt(reporte["totales"].get(c["clave"]), c["tipo"]) if n
                           else str(reporte["totales"].get(c["clave"], "")) for c, n in zip(columnas, numericas)])
        tabla = Table(cuerpo, repeatRows=1, hAlign="LEFT")
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3fb")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor(PALETA[0])),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 8), ("TEXTCOLOR", (0, 0), (-1, -1), tinta),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2 if tiene_totales else -1), [colors.white, colors.HexColor("#f7f7f5")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        estilo += [("ALIGN", (i, 1), (i, -1), "RIGHT") for i, n in enumerate(numericas) if n]
        if tiene_totales:
            estilo += [("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8),
                       ("LINEABOVE", (0, -1), (-1, -1), 0.8, tinta)]
        tabla.setStyle(TableStyle(estilo))
        elementos.append(tabla)

    def pie_de_pagina(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(secundaria)
        canvas.drawString(doc.leftMargin, 0.8 * cm, f"{reporte['empresa']} · FashionStore SaaS · Reporte generado con IA")
        canvas.drawRightString(pagina[0] - doc.rightMargin, 0.8 * cm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(elementos, onFirstPage=pie_de_pagina, onLaterPages=pie_de_pagina)
    return buffer.getvalue()


# ---------------------------------------------------------------- Excel
def a_excel(reporte: dict, narrativa: str | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.chart.series import DataPoint
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte"
    hex_ = lambda c: c.lstrip("#").upper()  # noqa: E731
    columnas = reporte["columnas"]
    ancho_titulo = max(len(columnas), 2)

    ws["A1"] = reporte["empresa"]
    ws["A1"].font = Font(size=10, color=hex_(TINTA_SECUNDARIA))
    ws["A2"] = reporte["titulo"]
    ws["A2"].font = Font(size=16, bold=True, color=hex_(TINTA))
    ws["A3"] = reporte["subtitulo"]
    ws["A4"] = f"Generado por {reporte['generado_por']} el {_fecha_local(reporte['generado_en'])}"
    ws["A4"].font = Font(italic=True, size=9, color=hex_(TINTA_SECUNDARIA))
    fila = 6
    for f in reporte["filtros"]:
        ws.cell(fila, 1, f["campo"]).font = Font(bold=True, size=9)
        ws.cell(fila, 2, f["valor"]).font = Font(size=9)
        fila += 1
    for s in reporte.get("supuestos") or []:
        ws.cell(fila, 1, f"Nota: {s}").font = Font(italic=True, size=9, color=hex_(TINTA_SECUNDARIA))
        fila += 1
    fila += 1

    formatos = {"moneda": "#,##0.00", "entero": "#,##0", "porcentaje": '0.0" %"'}
    encabezado = fila
    borde = Side(style="thin", color=hex_(PALETA[0]))
    for j, c in enumerate(columnas, start=1):
        celda = ws.cell(encabezado, j, c["titulo"])
        celda.font = Font(bold=True, color=hex_(TINTA))
        celda.fill = PatternFill("solid", fgColor="EEF3FB")
        celda.border = Border(bottom=borde)
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, f in enumerate(reporte["filas"], start=1):
        for j, c in enumerate(columnas, start=1):
            celda = ws.cell(encabezado + i, j, f.get(c["clave"]))
            if c["tipo"] in formatos:
                celda.number_format = formatos[c["tipo"]]
    ultima = encabezado + len(reporte["filas"])
    if reporte["totales"]:
        ultima += 1
        for j, c in enumerate(columnas, start=1):
            celda = ws.cell(ultima, j, reporte["totales"].get(c["clave"]))
            celda.font = Font(bold=True)
            celda.border = Border(top=Side(style="thin", color=hex_(TINTA)))
            if c["tipo"] in formatos:
                celda.number_format = formatos[c["tipo"]]
    ws.freeze_panes = ws.cell(encabezado + 1, 1)

    for j, c in enumerate(columnas, start=1):
        largo = max([len(str(c["titulo"]))] + [len(_fmt(f.get(c["clave"]), c["tipo"])) for f in reporte["filas"]])
        ws.column_dimensions[get_column_letter(j)].width = min(max(10, largo + 2), 45)

    fila_texto = ultima + 2
    if narrativa:
        ws.cell(fila_texto, 1, "Resumen").font = Font(bold=True)
        ws.cell(fila_texto + 1, 1, narrativa).alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=fila_texto + 1, start_column=1, end_row=fila_texto + 4, end_column=ancho_titulo)
        fila_texto += 6

    # Gráfico nativo de Excel sobre las mismas celdas
    g = reporte["grafico"]
    n = min(len(reporte["filas"]), MAX_CATEGORIAS_GRAFICO)
    if g["tipo"] != "tabla" and n and not reporte["vacio"]:
        claves = [c["clave"] for c in columnas]
        col_x = claves.index(g["eje_x"]) + 1 if g["eje_x"] in claves else 1
        categorias = Reference(ws, min_col=col_x, min_row=encabezado + 1, max_row=encabezado + n)
        if g["tipo"] == "torta":
            chart = PieChart()
            col = claves.index(g["series"][0]["clave"]) + 1
            chart.add_data(Reference(ws, min_col=col, min_row=encabezado, max_row=encabezado + n), titles_from_data=True)
            chart.set_categories(categorias)
            for i in range(n):
                punto = DataPoint(idx=i)
                punto.graphicalProperties.solidFill = hex_(PALETA[i]) if i < len(PALETA) else hex_(OTROS)
                punto.graphicalProperties.line.solidFill = "FFFFFF"
                chart.series[0].dPt.append(punto)
        else:
            chart = LineChart() if g["tipo"] == "lineas" else BarChart()
            if g["tipo"] == "barras":
                chart.type = "bar" if (n > 8 or g["eje_x"] in ("producto", "etiqueta")) else "col"
                chart.gapWidth = 60
            for i, s in enumerate(g["series"]):
                col = claves.index(s["clave"]) + 1
                chart.add_data(Reference(ws, min_col=col, min_row=encabezado, max_row=encabezado + n), titles_from_data=True)
                serie = chart.series[i]
                serie.graphicalProperties.line.solidFill = hex_(PALETA[i % len(PALETA)])
                if g["tipo"] == "lineas":
                    serie.graphicalProperties.line.width = 25400  # 2 pt
                    serie.smooth = False
                else:
                    serie.graphicalProperties.solidFill = hex_(PALETA[i % len(PALETA)])
            chart.set_categories(categorias)
            chart.x_axis.delete = chart.y_axis.delete = False   # openpyxl 3.1 oculta los ejes por defecto
            chart.y_axis.numFmt = "#,##0"
            if len(g["series"]) == 1:
                chart.legend = None   # una sola serie: el título la nombra
        chart.title = reporte["titulo"]
        chart.height, chart.width = 8, 16
        ws.add_chart(chart, ws.cell(fila_texto, 1).coordinate)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
