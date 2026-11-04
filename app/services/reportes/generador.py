"""Flujo completo: texto → intención → validación → consulta → reporte + narrativa (examen 8.1)."""
from app.core.contexto import Contexto
from app.schemas.reportes import Intencion
from app.services.reportes.catalogo import ReporteInvalido, ejemplos, validar
from app.services.reportes.consultas import ejecutar
from app.services.reportes.interprete import interpretar, narrar


def _respuesta(estado: str, texto: str, interprete: str, **extra) -> dict:
    base = {
        "estado": estado, "texto": texto, "interprete": interprete, "intencion": None, "supuestos": [],
        "mensaje": None, "sugerencias": [], "reporte": None, "narrativa": None, "narrativa_origen": None,
    }
    base.update(extra)
    if estado != "OK":
        base["sugerencias"] = ejemplos()
    return base


def ejecutar_intencion(ctx: Contexto, intencion: Intencion, avisos: list | None = None) -> tuple[dict, Intencion]:
    """Valida y ejecuta. Lanza ReporteInvalido si la intención no es aceptable."""
    validada = validar(ctx, intencion)
    reporte = ejecutar(ctx, validada)
    reporte["supuestos"] = [*(avisos or []), *reporte["supuestos"]]
    return reporte, validada.intencion


def generar_desde_texto(ctx: Contexto, texto: str, con_narrativa: bool = True) -> dict:
    interpretacion, interprete, aviso = interpretar(ctx, texto)
    avisos = [aviso] if aviso else []

    if interpretacion.estado == "NO_SOPORTADO":
        return _respuesta("NO_SOPORTADO", texto, interprete, supuestos=avisos,
                          mensaje=interpretacion.mensaje or "Ese pedido no corresponde a un reporte disponible.")
    if interpretacion.estado != "OK" or not interpretacion.tipo:
        return _respuesta("ACLARACION", texto, interprete, supuestos=avisos,
                          mensaje=interpretacion.mensaje or "No identifiqué qué reporte necesita.")
    if interpretacion.no_reconocidos:
        return _respuesta("ACLARACION", texto, interprete, supuestos=avisos,
                          mensaje=f"No encontré en su empresa: {', '.join(interpretacion.no_reconocidos)}. "
                                  "Revise el nombre de la sucursal, categoría o producto.")

    intencion = Intencion.model_validate(interpretacion.model_dump(include=set(Intencion.model_fields)))
    try:
        reporte, intencion = ejecutar_intencion(ctx, intencion, avisos)
    except ReporteInvalido as e:
        return _respuesta("ACLARACION", texto, interprete, supuestos=avisos, mensaje=e.mensaje)

    narrativa, origen = narrar(reporte, texto) if con_narrativa else (None, None)
    return _respuesta("OK", texto, interprete, intencion=intencion.model_dump(mode="json"),
                      supuestos=reporte["supuestos"], reporte=reporte, narrativa=narrativa, narrativa_origen=origen)
