"""Multitenant SaaS: empresas, planes, suscripciones y empresa_id en los datos de negocio

Revision ID: d1a7f3c2b9e0
Revises: c9fc05240596
Create Date: 2026-11-03

Migración defensiva: comprueba qué existe antes de crear, porque la base de producción se creó
con Base.metadata.create_all. Los datos existentes se asignan a la empresa original (FashionStore).
"""
from typing import Sequence, Union
from datetime import date

import sqlalchemy as sa
from alembic import op

revision: str = "d1a7f3c2b9e0"
down_revision: Union[str, Sequence[str], None] = "c9fc05240596"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMPRESA_BASE_ID = "00000000-0000-4000-8000-000000000001"
EMPRESA_BASE_SLUG = "fashionstore"

TABLAS_TENANT = [
    "sucursales", "usuarios", "categorias", "proveedores", "prendas", "variantes_prenda",
    "inventarios", "temporadas", "colecciones", "ordenes", "reservas", "bitacora",
]
# usuarios: el Administrador de plataforma no tiene empresa. bitacora: acciones de plataforma.
TABLAS_TENANT_NULLABLE = {"usuarios", "bitacora"}

PLANES = [
    # codigo, nombre, precio, max_sucursales, max_usuarios, offline, reportes_ia
    ("BASICO", "Básico", 150.0, 2, None, True, False),
    ("PROFESIONAL", "Profesional", 450.0, 10, None, True, True),
]


def _insp():
    return sa.inspect(op.get_bind())


def _tabla_existe(tabla: str) -> bool:
    return tabla in _insp().get_table_names()


def _columna_existe(tabla: str, columna: str) -> bool:
    return columna in {c["name"] for c in _insp().get_columns(tabla)}


def _agregar_columna(tabla: str, columna: sa.Column, fk=None, unica=False):
    if not _tabla_existe(tabla) or _columna_existe(tabla, columna.name):
        return
    op.add_column(tabla, columna)
    if fk:
        op.create_foreign_key(f"fk_{tabla}_{columna.name}", tabla, fk, [columna.name], ["id"])
    if unica:
        op.create_unique_constraint(f"uq_{tabla}_{columna.name}", tabla, [columna.name])


def _sincronizar_secuencias(bind) -> None:
    """Si se insertaron filas con id explícito, la secuencia SERIAL queda atrasada y el siguiente
    INSERT choca con la llave primaria. Se ajusta cada secuencia al MAX(id) actual."""
    if bind.dialect.name != "postgresql":
        return
    for tabla in _insp().get_table_names():
        if "id" not in {c["name"] for c in _insp().get_columns(tabla)}:
            continue
        secuencia = bind.execute(sa.text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": tabla}).scalar()
        if secuencia:
            bind.execute(sa.text(
                f'SELECT setval(:s, COALESCE((SELECT MAX(id) FROM "{tabla}"), 1), '
                f'(SELECT MAX(id) FROM "{tabla}") IS NOT NULL)'
            ), {"s": secuencia})


def upgrade() -> None:
    bind = op.get_bind()
    _sincronizar_secuencias(bind)

    # 1. Tablas de la plataforma SaaS
    if not _tabla_existe("planes"):
        op.create_table(
            "planes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("codigo", sa.String(30), nullable=False, unique=True),
            sa.Column("nombre", sa.String(60), nullable=False),
            sa.Column("precio_mensual", sa.Float(), nullable=False, server_default="0"),
            sa.Column("max_sucursales", sa.Integer(), nullable=False),
            sa.Column("max_usuarios", sa.Integer(), nullable=True),
            sa.Column("permite_offline", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("permite_reportes_ia", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.create_index("ix_planes_id", "planes", ["id"])

    if not _tabla_existe("empresas"):
        op.create_table(
            "empresas",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("razon_social", sa.String(150), nullable=False),
            sa.Column("nit", sa.String(30), nullable=False, unique=True),
            sa.Column("slug", sa.String(60), nullable=False),
            sa.Column("correo", sa.String(100)),
            sa.Column("telefono", sa.String(30)),
            sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVA"),
            sa.Column("fecha_registro", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_empresas_slug", "empresas", ["slug"], unique=True)

    if not _tabla_existe("suscripciones"):
        op.create_table(
            "suscripciones",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("empresa_id", sa.String(36), sa.ForeignKey("empresas.id"), nullable=False),
            sa.Column("plan_id", sa.Integer(), sa.ForeignKey("planes.id"), nullable=False),
            sa.Column("fecha_inicio", sa.Date(), nullable=False),
            sa.Column("fecha_fin", sa.Date(), nullable=False),
            sa.Column("estado", sa.String(20), nullable=False, server_default="ACTIVA"),
            sa.Column("periodicidad", sa.String(20), nullable=False, server_default="MENSUAL"),
            sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_suscripciones_id", "suscripciones", ["id"])
        op.create_index("ix_suscripciones_empresa_id", "suscripciones", ["empresa_id"])

    # 2. Planes base (configurables luego desde /api/plataforma/planes)
    for codigo, nombre, precio, max_suc, max_usr, offline, ia in PLANES:
        existe = bind.execute(sa.text("SELECT 1 FROM planes WHERE codigo = :c"), {"c": codigo}).first()
        if not existe:
            bind.execute(
                sa.text(
                    "INSERT INTO planes (codigo, nombre, precio_mensual, max_sucursales, max_usuarios, "
                    "permite_offline, permite_reportes_ia, activo) "
                    "VALUES (:c, :n, :p, :ms, :mu, :o, :ia, true)"
                ),
                {"c": codigo, "n": nombre, "p": precio, "ms": max_suc, "mu": max_usr, "o": offline, "ia": ia},
            )

    # 3. Empresa original (dueña de todos los datos existentes) con plan Profesional anual
    fila = bind.execute(sa.text("SELECT id FROM empresas WHERE slug = :s"), {"s": EMPRESA_BASE_SLUG}).first()
    empresa_base = fila[0] if fila else EMPRESA_BASE_ID
    if not fila:
        bind.execute(
            sa.text(
                "INSERT INTO empresas (id, razon_social, nit, slug, estado) "
                "VALUES (:id, 'FashionStore S.R.L.', '1000000001', :s, 'ACTIVA')"
            ),
            {"id": empresa_base, "s": EMPRESA_BASE_SLUG},
        )
    tiene_suscripcion = bind.execute(
        sa.text("SELECT 1 FROM suscripciones WHERE empresa_id = :e"), {"e": empresa_base}
    ).first()
    if not tiene_suscripcion:
        hoy = date.today()
        bind.execute(
            sa.text(
                "INSERT INTO suscripciones (empresa_id, plan_id, fecha_inicio, fecha_fin, estado, periodicidad) "
                "SELECT :e, id, :ini, :fin, 'ACTIVA', 'ANUAL' FROM planes WHERE codigo = 'PROFESIONAL'"
            ),
            {"e": empresa_base, "ini": hoy, "fin": date(hoy.year + 1, hoy.month, min(hoy.day, 28))},
        )

    # 4. empresa_id en todas las tablas de negocio
    for tabla in TABLAS_TENANT:
        if not _tabla_existe(tabla):
            continue
        if not _columna_existe(tabla, "empresa_id"):
            op.add_column(tabla, sa.Column("empresa_id", sa.String(36), nullable=True))
            op.create_foreign_key(f"fk_{tabla}_empresa_id", tabla, "empresas", ["empresa_id"], ["id"])
            op.create_index(f"ix_{tabla}_empresa_id", tabla, ["empresa_id"])
        bind.execute(sa.text(f"UPDATE {tabla} SET empresa_id = :e WHERE empresa_id IS NULL"), {"e": empresa_base})
        if tabla not in TABLAS_TENANT_NULLABLE:
            op.alter_column(tabla, "empresa_id", existing_type=sa.String(36), nullable=False)

    # 5. Sucursales activas/inactivas (límite del plan)
    _agregar_columna("sucursales", sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()))

    # 6. Datos de venta exigidos (7.2) e idempotencia de sincronización
    _agregar_columna("ordenes", sa.Column("canal", sa.String(20), nullable=True))
    _agregar_columna("ordenes", sa.Column("metodo_pago", sa.String(20), nullable=True))
    _agregar_columna("ordenes", sa.Column("sucursal_id", sa.Integer(), nullable=True), fk="sucursales")
    _agregar_columna("ordenes", sa.Column("usuario_id", sa.Integer(), nullable=True), fk="usuarios")
    _agregar_columna("ordenes", sa.Column("cliente_id", sa.Integer(), nullable=True), fk="usuarios")
    _agregar_columna("ordenes", sa.Column("uuid_operacion", sa.String(36), nullable=True), unica=True)
    if _tabla_existe("ordenes"):
        if "ix_ordenes_sucursal_id" not in {i["name"] for i in _insp().get_indexes("ordenes")}:
            op.create_index("ix_ordenes_sucursal_id", "ordenes", ["sucursal_id"])
        bind.execute(sa.text(
            "UPDATE ordenes SET canal = CASE WHEN direccion_envio = 'Venta en Tienda Física' "
            "THEN 'PRESENCIAL' ELSE 'WEB' END WHERE canal IS NULL"
        ))
    _agregar_columna("reservas", sa.Column("usuario_id", sa.Integer(), nullable=True), fk="usuarios")
    _agregar_columna("reservas", sa.Column("uuid_operacion", sa.String(36), nullable=True), unica=True)

    # 7. SKU único por empresa (antes era único en toda la base)
    if _tabla_existe("variantes_prenda"):
        insp = _insp()
        for idx in insp.get_indexes("variantes_prenda"):
            if idx["column_names"] == ["codigo_sku"] and idx.get("unique"):
                op.drop_index(idx["name"], table_name="variantes_prenda")
                op.create_index("ix_variantes_prenda_codigo_sku", "variantes_prenda", ["codigo_sku"])
        for uc in insp.get_unique_constraints("variantes_prenda"):
            if uc["column_names"] == ["codigo_sku"]:
                op.drop_constraint(uc["name"], "variantes_prenda", type_="unique")
        nombres = {uc["name"] for uc in _insp().get_unique_constraints("variantes_prenda")}
        if "uq_variante_empresa_sku" not in nombres:
            op.create_unique_constraint("uq_variante_empresa_sku", "variantes_prenda", ["empresa_id", "codigo_sku"])

    # 8. Rol del proveedor SaaS
    if _tabla_existe("roles"):
        existe = bind.execute(sa.text("SELECT 1 FROM roles WHERE nombre = 'Administrador de plataforma'")).first()
        if not existe:
            bind.execute(sa.text(
                "INSERT INTO roles (nombre, descripcion) VALUES "
                "('Administrador de plataforma', 'Proveedor del servicio SaaS: empresas, planes y suscripciones')"
            ))


def downgrade() -> None:
    op.drop_constraint("uq_variante_empresa_sku", "variantes_prenda", type_="unique")
    for tabla, columna in [
        ("reservas", "uuid_operacion"), ("reservas", "usuario_id"),
        ("ordenes", "uuid_operacion"), ("ordenes", "cliente_id"), ("ordenes", "usuario_id"),
        ("ordenes", "sucursal_id"), ("ordenes", "metodo_pago"), ("ordenes", "canal"),
        ("sucursales", "activa"),
    ]:
        op.drop_column(tabla, columna)
    for tabla in TABLAS_TENANT:
        op.drop_column(tabla, "empresa_id")
    op.drop_table("suscripciones")
    op.drop_table("empresas")
    op.drop_table("planes")
