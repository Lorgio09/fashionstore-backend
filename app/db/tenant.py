"""
Aislamiento multitenant a nivel de ORM.

Cada modelo que pertenece a una empresa hereda de ``TenantMixin`` (columna ``empresa_id``).
Dos eventos de SQLAlchemy garantizan el aislamiento en el backend (RN02, RN03, RNF02):

1. ``do_orm_execute``: a toda consulta SELECT sobre modelos con ``TenantMixin`` se le agrega
   ``WHERE empresa_id = <empresa del usuario>``. Si no hay empresa en la sesión, la consulta
   se rechaza (fail-closed): olvidarse del contexto produce un error, nunca una fuga de datos.
2. ``before_flush``: los registros nuevos reciben automáticamente la empresa de la sesión y se
   impide guardar o modificar un registro de otra empresa.

El contexto se fija por request con ``set_tenant(session, empresa_id)`` (ver app/core/contexto.py).
Solo el Administrador de plataforma y los procesos internos usan ``set_global(session)``.
"""
from sqlalchemy import Column, ForeignKey, String, event
from sqlalchemy.orm import Session, declared_attr, with_loader_criteria

CLAVE_EMPRESA = "empresa_id"
CLAVE_GLOBAL = "modo_global"


class TenantNoDefinido(RuntimeError):
    """Se intentó leer o escribir datos de una empresa sin contexto de tenant."""


class AccesoCruzado(PermissionError):
    """Se intentó escribir un registro que pertenece a otra empresa."""


class TenantMixin:
    """Marca un modelo como dato de una empresa (tenant)."""

    __tenant_nullable__ = False

    @declared_attr
    def empresa_id(cls):
        return Column(
            String(36),
            ForeignKey("empresas.id"),
            nullable=cls.__tenant_nullable__,
            index=True,
        )


def set_tenant(session: Session, empresa_id: str) -> None:
    session.info[CLAVE_EMPRESA] = empresa_id
    session.info.pop(CLAVE_GLOBAL, None)


def set_global(session: Session) -> None:
    session.info.pop(CLAVE_EMPRESA, None)
    session.info[CLAVE_GLOBAL] = True


def tenant_actual(session: Session):
    return session.info.get(CLAVE_EMPRESA)


def _es_modelo_tenant(mapper) -> bool:
    return issubclass(mapper.class_, TenantMixin)


@event.listens_for(Session, "do_orm_execute")
def _filtrar_por_empresa(estado):
    if not estado.is_select or estado.is_column_load or estado.is_relationship_load:
        return
    if estado.execution_options.get("sin_tenant") or estado.session.info.get(CLAVE_GLOBAL):
        return

    empresa_id = estado.session.info.get(CLAVE_EMPRESA)
    if empresa_id is None:
        if any(_es_modelo_tenant(m) for m in estado.all_mappers):
            raise TenantNoDefinido("Consulta a datos de empresa sin contexto de tenant")
        return

    estado.statement = estado.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.empresa_id == empresa_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _asignar_y_validar_empresa(session, flush_context, instances):
    if session.info.get(CLAVE_GLOBAL):
        return
    empresa_id = session.info.get(CLAVE_EMPRESA)

    for obj in session.new:
        if not isinstance(obj, TenantMixin):
            continue
        if obj.empresa_id is None:
            if empresa_id is None:
                if obj.__tenant_nullable__:
                    continue
                raise TenantNoDefinido(f"No se puede crear {type(obj).__name__} sin empresa")
            obj.empresa_id = empresa_id
        elif empresa_id is not None and obj.empresa_id != empresa_id:
            raise AccesoCruzado("No puede crear registros en otra empresa")

    if empresa_id is None:
        return
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, TenantMixin) and obj.empresa_id not in (None, empresa_id):
            raise AccesoCruzado("No puede modificar registros de otra empresa")
