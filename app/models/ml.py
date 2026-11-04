from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.orm import relationship

from app.db.database import Base
from app.db.tenant import TenantMixin

MODELO_DEMANDA = "DEMANDA"
MODELO_SEGMENTACION = "SEGMENTACION"


class ModeloML(TenantMixin, Base):
    """Modelo de Machine Learning entrenado con los datos de UNA empresa (examen 8.4).

    El modelo serializado se guarda en la base (no en disco) porque el disco del servidor en la nube
    se borra en cada despliegue. Se conservan todas las versiones; solo una está activa por tipo.
    """
    __tablename__ = "modelos_ml"
    __table_args__ = (Index("ix_modelos_ml_empresa_tipo", "empresa_id", "tipo", "activo"),)

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String(20), nullable=False)              # DEMANDA | SEGMENTACION
    version = Column(Integer, nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    algoritmo = Column(String(60), nullable=False)
    entrenado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    entrenado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    duracion_s = Column(Integer, nullable=True)

    parametros = Column(JSON, nullable=False)      # hiperparámetros y variables usadas
    datos = Column(JSON, nullable=False)           # rango de fechas y tamaño del conjunto de entrenamiento
    metricas = Column(JSON, nullable=False)        # evaluación y validación
    artefacto = Column(LargeBinary, nullable=False)  # modelo serializado (joblib)

    usuario = relationship("Usuario")
