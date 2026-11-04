"""Persistencia de los modelos entrenados en PostgreSQL, con versiones (examen 8.4, punto 6)."""
from io import BytesIO
from typing import Optional

import joblib
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ml import ModeloML

_cache: dict = {}   # (empresa_id, tipo, version) -> artefacto ya deserializado


def guardar(db: Session, empresa_id: str, tipo: str, algoritmo: str, artefacto: dict, metricas: dict,
            parametros: dict, datos: dict, usuario_id: Optional[int]) -> ModeloML:
    buffer = BytesIO()
    joblib.dump(artefacto, buffer, compress=3)
    version = (db.query(func.max(ModeloML.version))
               .filter(ModeloML.empresa_id == empresa_id, ModeloML.tipo == tipo).scalar() or 0) + 1
    db.query(ModeloML).filter(ModeloML.empresa_id == empresa_id, ModeloML.tipo == tipo,
                              ModeloML.activo.is_(True)).update({"activo": False}, synchronize_session=False)
    registro = ModeloML(tipo=tipo, version=version, activo=True, algoritmo=algoritmo, entrenado_por=usuario_id,
                        duracion_s=int(round(datos.get("segundos", 0))), parametros=parametros, datos=datos,
                        metricas=metricas, artefacto=buffer.getvalue(), empresa_id=empresa_id)
    db.add(registro)
    db.flush()
    _cache[(empresa_id, tipo, version)] = artefacto
    return registro


def activo(db: Session, empresa_id: str, tipo: str) -> Optional[ModeloML]:
    return (db.query(ModeloML)
            .filter(ModeloML.empresa_id == empresa_id, ModeloML.tipo == tipo, ModeloML.activo.is_(True))
            .order_by(ModeloML.version.desc()).first())


def cargar(registro: ModeloML) -> dict:
    """Los modelos solo los genera el propio backend al entrenar; nunca se cargan archivos externos."""
    clave = (registro.empresa_id, registro.tipo, registro.version)
    if clave not in _cache:
        _cache[clave] = joblib.load(BytesIO(registro.artefacto))
    return _cache[clave]
