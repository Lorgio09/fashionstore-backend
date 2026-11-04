"""Módulo de Machine Learning: tabla modelos_ml

Revision ID: a4d9e2b8c6f1
Revises: f2b7c9e3a1d6
Create Date: 2026-11-04

Defensiva: main.py todavía ejecuta create_all, así que la tabla puede existir.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4d9e2b8c6f1"
down_revision: Union[str, Sequence[str], None] = "f2b7c9e3a1d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "modelos_ml"


def upgrade() -> None:
    if TABLA in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        TABLA,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("empresa_id", sa.String(36), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("algoritmo", sa.String(60), nullable=False),
        sa.Column("entrenado_en", sa.DateTime(), nullable=False),
        sa.Column("entrenado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("duracion_s", sa.Integer(), nullable=True),
        sa.Column("parametros", sa.JSON(), nullable=False),
        sa.Column("datos", sa.JSON(), nullable=False),
        sa.Column("metricas", sa.JSON(), nullable=False),
        sa.Column("artefacto", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_modelos_ml_id", TABLA, ["id"])
    op.create_index("ix_modelos_ml_empresa_id", TABLA, ["empresa_id"])
    op.create_index("ix_modelos_ml_empresa_tipo", TABLA, ["empresa_id", "tipo", "activo"])


def downgrade() -> None:
    if TABLA in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLA)
