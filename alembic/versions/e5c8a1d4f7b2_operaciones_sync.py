"""Sincronización offline: tabla operaciones_sync

Revision ID: e5c8a1d4f7b2
Revises: d1a7f3c2b9e0
Create Date: 2026-11-03

Defensiva como la anterior: main.py todavía ejecuta create_all, así que la tabla puede existir.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5c8a1d4f7b2"
down_revision: Union[str, Sequence[str], None] = "d1a7f3c2b9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "operaciones_sync"


def upgrade() -> None:
    if TABLA in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        TABLA,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("empresa_id", sa.String(36), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("uuid", sa.String(36), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), sa.ForeignKey("sucursales.id"), nullable=True),
        sa.Column("dispositivo_id", sa.String(64), nullable=True),
        sa.Column("creado_en_dispositivo", sa.DateTime(), nullable=True),
        sa.Column("recibido_en", sa.DateTime(), nullable=False),
        sa.Column("procesado_en", sa.DateTime(), nullable=False),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("datos", sa.JSON(), nullable=False),
        sa.Column("servidor_id", sa.Integer(), nullable=True),
        sa.Column("mensaje", sa.String(255), nullable=True),
        sa.Column("detalle", sa.JSON(), nullable=True),
        sa.Column("resuelto_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("resuelto_en", sa.DateTime(), nullable=True),
        sa.Column("resolucion", sa.String(20), nullable=True),
    )
    op.create_index("ix_operaciones_sync_id", TABLA, ["id"])
    op.create_index("ix_operaciones_sync_uuid", TABLA, ["uuid"], unique=True)
    op.create_index("ix_operaciones_sync_empresa_id", TABLA, ["empresa_id"])
    op.create_index("ix_operaciones_sync_estado", TABLA, ["estado"])
    op.create_index("ix_operaciones_sync_sucursal_id", TABLA, ["sucursal_id"])


def downgrade() -> None:
    if TABLA in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLA)
