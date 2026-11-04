"""Posventa (devoluciones, cambios, notas de crédito, movimientos de inventario) y caja

Revision ID: b7e3f1a9d2c4
Revises: a4d9e2b8c6f1
Create Date: 2026-11-04

Las tablas se crean a partir de los modelos (checkfirst: main.py todavía ejecuta create_all).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e3f1a9d2c4"
down_revision: Union[str, Sequence[str], None] = "a4d9e2b8c6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Orden de creación según las claves foráneas
TABLAS = ["politicas_devolucion", "notas_credito", "solicitudes_devolucion", "detalles_solicitud",
          "movimientos_nota_credito", "movimientos_inventario", "turnos_caja"]


def upgrade() -> None:
    from app import models  # noqa: F401
    from app.db.database import Base

    bind = op.get_bind()
    for tabla in TABLAS:
        Base.metadata.tables[tabla].create(bind, checkfirst=True)
    columnas = {c["name"] for c in sa.inspect(bind).get_columns("inventarios")}
    if "stock_no_disponible" not in columnas:
        op.add_column("inventarios", sa.Column("stock_no_disponible", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    from app import models  # noqa: F401
    from app.db.database import Base

    bind = op.get_bind()
    for tabla in reversed(TABLAS):
        Base.metadata.tables[tabla].drop(bind, checkfirst=True)
    if "stock_no_disponible" in {c["name"] for c in sa.inspect(bind).get_columns("inventarios")}:
        op.drop_column("inventarios", "stock_no_disponible")
