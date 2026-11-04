"""
Prepara la base de datos antes de levantar la API (se usa en el Start Command de Render).

    python -m scripts.inicializar_bd

- Base vacía (sin tablas): crea todas las tablas desde los modelos actuales y la marca en la última
  migración (`alembic stamp head`). Es lo que recomienda Alembic para instalaciones nuevas: la historia
  de migraciones empieza en una base creada en el parcial 1 con create_all y un parche manual.
- Base existente: aplica las migraciones pendientes (`alembic upgrade head`).
"""
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app import models  # noqa: F401  (registra todos los modelos)
from app.db.database import Base, engine

RAIZ = Path(__file__).resolve().parent.parent


def main() -> int:
    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    tablas = set(sa.inspect(engine).get_table_names())
    if not tablas - {"alembic_version"}:
        print("Base vacía: se crean las tablas y se marca la última migración.")
        Base.metadata.create_all(bind=engine)
        command.stamp(config, "head")
    else:
        print("Base existente: se aplican las migraciones pendientes.")
        command.upgrade(config, "head")
    return 0


if __name__ == "__main__":
    sys.exit(main())
