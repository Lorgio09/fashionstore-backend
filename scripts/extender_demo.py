"""
Extiende las ventas sintéticas de la empresa demo "Estilo Urbano" hasta hoy (hora de Bolivia).

El historial demo se generó una sola vez (scripts/seed_demo.py) y termina el día anterior a la siembra.
Con el paso de los días, el dashboard de ML y los reportes mostraban una caída artificial a cero.
Este script agrega solo los días que faltan, continuando la misma tendencia; repetirlo no duplica nada.

Uso (desde fashionstore-backend):
    venv\Scripts\python -m scripts.extender_demo                # hasta hoy, base del .env
    venv\Scripts\python -m scripts.extender_demo --hasta 2026-11-09
    venv\Scripts\python -m scripts.extender_demo --entrenar     # además reentrena los modelos de ML
"""
import argparse
import sys
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

from sqlalchemy import func  # noqa: E402

from app import models as _modelos  # noqa: E402,F401
from app.db.database import SessionLocal  # noqa: E402
from app.db.tenant import set_global  # noqa: E402
from app.ml import datos_sinteticos as sinteticos  # noqa: E402
from app.models.inventario import Orden  # noqa: E402
from app.models.saas import Empresa  # noqa: E402
from app.models.usuarios import Usuario  # noqa: E402

DIRECCIONES_SINTETICAS = ("Venta en tienda física", "Envío a domicilio")


def _local(utc: datetime) -> date:
    return (utc + timedelta(hours=sinteticos.OFFSET_HORAS)).date()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hasta", type=date.fromisoformat,
                        default=_local(datetime.now(timezone.utc).replace(tzinfo=None)))
    parser.add_argument("--entrenar", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    set_global(db)
    try:
        eu = db.query(Empresa).filter(Empresa.slug == "estilo-urbano").one()
        sinteticas = db.query(func.min(Orden.fecha_orden), func.max(Orden.fecha_orden)).filter(
            Orden.empresa_id == eu.id, Orden.direccion_envio.in_(DIRECCIONES_SINTETICAS)).one()
        if sinteticas[0] is None:
            print("Estilo Urbano no tiene ventas sintéticas: ejecute primero scripts.seed_demo")
            return 1
        origen, ultimo = _local(sinteticas[0]), _local(sinteticas[1])
        desde = ultimo + timedelta(days=1)
        print(f"Ventas sintéticas: del {origen} al {ultimo}.")
        if desde > args.hasta:
            print(f"Nada que agregar (ya llegan hasta {args.hasta}).")
        else:
            sucursales, prendas = sinteticos.cargar_catalogo(db, eu.id)
            clientes = sinteticos.cargar_clientes(db, eu.id)
            usuarios = {u.email: u.id for u in db.query(Usuario).filter(Usuario.empresa_id == eu.id)}
            equipetrol, centro, norte = sucursales
            personal = {equipetrol.id: usuarios["encargado@estilourbano.com"],
                        centro.id: usuarios["cajero@estilourbano.com"], norte.id: usuarios["admin@estilourbano.com"]}
            n = sinteticos.generar_ventas(db, eu.id, sucursales, prendas, clientes, personal, hasta=args.hasta,
                                          desde=desde, origen=origen, semilla=sinteticos.SEMILLA + desde.toordinal())
            db.commit()
            print(f"+ {n} ventas del {desde} al {args.hasta}.")

        if args.entrenar:
            from app.core.contexto import Contexto
            from app.db.tenant import set_tenant
            from app.ml import servicio
            admin = db.query(Usuario).filter(Usuario.email == "admin@estilourbano.com").one()
            set_tenant(db, eu.id)
            ctx = Contexto(db=db, usuario=admin, empresa=eu)
            r = servicio.entrenar(ctx)
            print("Modelos reentrenados:", {k: v.get("version") for k, v in r.items() if isinstance(v, dict)})
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
