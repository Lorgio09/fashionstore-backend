"""
Reportes generativos mediante IA (examen, Desafío V).

Flujo: texto o voz → la IA propone una intención (JSON) → el backend la valida contra un catálogo
cerrado → ejecuta una consulta propia filtrada por empresa → tabla, gráfico y análisis → PDF/Excel.
Solo plan Profesional con suscripción vigente; Administrador y Encargado (este, solo su sucursal).
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.core.contexto import Contexto, requiere_funcion
from app.core.security import registrar_bitacora
from app.schemas.reportes import EjecutarReporte, ExportarReporte, SolicitudReporte, VozRequest
from app.services.reportes import exportacion
from app.services.reportes.catalogo import TIPOS, ReporteInvalido, ejemplos
from app.services.reportes.generador import ejecutar_intencion, generar_desde_texto
from app.services.reportes.interprete import ia_configurada

router = APIRouter()
contexto_ia = requiere_funcion("reportes_ia")

TIPOS_ARCHIVO = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get("/reportes/tipos", summary="Catálogo de reportes disponibles, ejemplos y paleta de colores")
def tipos_de_reporte(ctx: Contexto = Depends(contexto_ia)):
    return {
        "tipos": [
            {"codigo": t.codigo, "nombre": t.nombre, "descripcion": t.descripcion, "usa_fechas": t.usa_fechas,
             "filtros": ["sucursales", *t.filtros], "grafico": t.grafico, "ejemplos": list(t.ejemplos)}
            for t in TIPOS.values()
        ],
        "ejemplos": ejemplos(),
        "paleta": exportacion.PALETA,
        "ia_disponible": ia_configurada(),
    }


@router.post("/reportes", summary="Generar un reporte a partir de lenguaje natural (escrito o voz transcrita)")
def generar_reporte(solicitud: SolicitudReporte, ctx: Contexto = Depends(contexto_ia)):
    resultado = generar_desde_texto(ctx, solicitud.texto.strip(), solicitud.narrativa)
    registrar_bitacora(ctx.db, ctx.usuario.id, "REPORTE_IA", "reportes", 0,
                       f"{resultado['estado']} {(resultado['intencion'] or {}).get('tipo', '-')}: {solicitud.texto}")
    return resultado


@router.post("/reportes/ejecutar", summary="Volver a ejecutar un reporte con filtros editados (sin IA)")
def ejecutar_reporte(cuerpo: EjecutarReporte, ctx: Contexto = Depends(contexto_ia)):
    try:
        reporte, intencion = ejecutar_intencion(ctx, cuerpo.intencion)
    except ReporteInvalido as e:
        raise HTTPException(status_code=422, detail=e.mensaje)
    return {"intencion": intencion.model_dump(mode="json"), "reporte": reporte}


@router.post("/reportes/exportar", summary="Exportar un reporte a PDF o Excel",
             responses={200: {"content": {v: {} for v in TIPOS_ARCHIVO.values()}}})
def exportar_reporte(cuerpo: ExportarReporte, ctx: Contexto = Depends(contexto_ia)):
    try:
        reporte, _ = ejecutar_intencion(ctx, cuerpo.intencion)
    except ReporteInvalido as e:
        raise HTTPException(status_code=422, detail=e.mensaje)
    generar = exportacion.a_pdf if cuerpo.formato == "pdf" else exportacion.a_excel
    contenido = generar(reporte, cuerpo.narrativa)
    registrar_bitacora(ctx.db, ctx.usuario.id, "EXPORTAR_REPORTE", "reportes", 0,
                       f"{reporte['tipo']} en {cuerpo.formato.upper()}")
    archivo = exportacion.nombre_archivo(reporte, cuerpo.formato)
    return Response(contenido, media_type=TIPOS_ARCHIVO[cuerpo.formato],
                    headers={"Content-Disposition": f'attachment; filename="{archivo}"'})


@router.post("/generar-reporte", deprecated=True, summary="Obsoleto: usar POST /ia/reportes")
def generar_reporte_compatible(request: VozRequest, ctx: Contexto = Depends(contexto_ia)):
    """Mantiene funcionando la pantalla actual de la web hasta que se migre a /ia/reportes."""
    resultado = generar_desde_texto(ctx, request.texto_voz.strip())
    return {"reporte": resultado["narrativa"] or resultado["mensaje"], "modelo_usado": resultado["interprete"],
            "resultado": resultado}
