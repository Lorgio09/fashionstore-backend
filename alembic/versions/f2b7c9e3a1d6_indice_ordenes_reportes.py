"""Índice de ventas por empresa y fecha para los reportes (RNF09)

Revision ID: f2b7c9e3a1d6
Revises: e5c8a1d4f7b2
Create Date: 2026-11-04

Todos los reportes de ventas filtran por empresa_id y por un rango de fecha_orden.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b7c9e3a1d6"
down_revision: Union[str, Sequence[str], None] = "e5c8a1d4f7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDICE = "ix_ordenes_empresa_fecha"


def _existe() -> bool:
    return INDICE in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("ordenes")}


def upgrade() -> None:
    if not _existe():
        op.create_index(INDICE, "ordenes", ["empresa_id", "fecha_orden"])


def downgrade() -> None:
    if _existe():
        op.drop_index(INDICE, table_name="ordenes")
