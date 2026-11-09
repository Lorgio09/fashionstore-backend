"""
CU-19: cambio de prenda sin conexión (operación offline tipo CAMBIO, contrato §6.5).
Idempotencia, mismas reglas que el cambio en línea, conflicto de stock, nota de crédito y caja.
"""
from datetime import datetime, timedelta
from uuid import uuid4

from app.db.database import SessionLocal
from app.db.tenant import set_global
from app.models.inventario import Inventario
from tests.test_posventa import extra, linea, orden_directa, stock, vender  # noqa: F401  (fixture extra)
from tests.test_sync import enviar, sesion, venta  # noqa: F401  (fixture sesion)

D = "/api/devoluciones"


def _ahora(segundos=0) -> str:
    return (datetime.utcnow() + timedelta(seconds=segundos)).isoformat() + "Z"


def cambio(s, datos, entregados, diferencia=0.0, orden_id=None, venta_uuid=None, devueltos=None,
           creado_en=None, **campos):
    return {
        "uuid": str(uuid4()), "tipo": "CAMBIO", "empresa_id": s["empresa"], "sucursal_id": datos["a"]["sucursal"],
        "usuario_id": s["id"], "creado_en": creado_en or _ahora(),
        "datos": {"orden_id": orden_id, "venta_uuid": venta_uuid, "motivo": campos.pop("motivo", "TALLA"),
                  "devueltos": devueltos or [{"variante_id": datos["a"]["variante"], "cantidad": 1}],
                  "entregados": entregados, "diferencia": diferencia, **campos},
    }


def _fijar_stock(variante_id, sucursal_id, cantidad):
    db = SessionLocal()
    set_global(db)
    db.query(Inventario).filter(Inventario.variante_id == variante_id, Inventario.sucursal_id == sucursal_id) \
        .update({"stock_disponible": cantidad})
    db.commit()
    db.close()


def test_cambio_de_talla_offline_confirmado_e_idempotente(client, datos, extra, sesion, token):
    cajero = sesion("cajero@a.com")
    a = datos["a"]
    orden = vender(client, cajero["h"], datos)["orden_id"]           # M: 10 -> 9
    op = cambio(cajero, datos, [{"variante_id": extra["talla_l"], "cantidad": 1, "precio_unitario": 100}],
                orden_id=orden, devueltos=[{"detalle_orden_id": linea(client, cajero["h"], orden), "cantidad": 1}])

    [r] = enviar(client, cajero, op)
    assert r["estado"] == "CONFIRMADA", r
    codigo = r["detalle"]["codigo"]
    assert codigo.startswith("DEV-") and r["detalle"]["resolucion"] == "CAMBIO_VARIANTE"
    assert r["detalle"]["diferencia_calculada"] == 0 and r["detalle"]["nota_credito"] is None
    assert stock(a["variante"], a["sucursal"])[0] == 10                # la M devuelta vuelve al stock
    assert stock(extra["talla_l"], a["sucursal"])[0] == 4              # la L entregada sale

    [r2] = enviar(client, cajero, op)                                  # reenvío: no duplica
    assert r2["duplicada"] and r2["servidor_id"] == r["servidor_id"]
    assert stock(extra["talla_l"], a["sucursal"])[0] == 4

    sol = client.get(f"{D}/solicitudes/{codigo}", headers=token("admin@a.com")).json()
    assert sol["estado"] == "CAMBIO_REALIZADO" and sol["canal"] == "OFFLINE" and sol["inspeccion"] == "APTA"
    assert sol["items"][0]["entregado"]["talla"] == "L" and sol["acciones"] == []
    # La línea ya quedó devuelta: un segundo cambio de la misma unidad se rechaza
    [r3] = enviar(client, cajero, cambio(cajero, datos, [{"variante_id": extra["talla_l"], "cantidad": 1,
                                                          "precio_unitario": 100}], orden_id=orden))
    assert r3["estado"] == "RECHAZADA" and "elegibles" in r3["mensaje"]


def test_cambio_de_venta_offline_en_el_mismo_lote_cobra_la_diferencia_en_caja(client, datos, extra, sesion):
    cajero = sesion("cajero@a.com")
    assert client.post("/api/caja/abrir", json={"fondo_inicial": 100}, headers=cajero["h"]).status_code == 201
    op_venta = venta(cajero, datos, creado_en=_ahora())
    # El cambio se envía primero en el lote, pero ocurrió después: el servidor respeta el orden real
    op_cambio = cambio(cajero, datos, [{"variante_id": extra["cara"], "cantidad": 1, "precio_unitario": 180}],
                       diferencia=80, forma_cobro="EFECTIVO", venta_uuid=op_venta["uuid"], creado_en=_ahora(0.001),
                       motivo="YA_NO_LO_DESEA")
    r_cambio, r_venta = enviar(client, cajero, op_cambio, op_venta)
    assert r_venta["estado"] == "CONFIRMADA" and r_cambio["estado"] == "CONFIRMADA", r_cambio
    assert r_cambio["detalle"]["resolucion"] == "CAMBIO_PRODUCTO" and r_cambio["detalle"]["monto_cobrado"] == 80

    arqueo = client.get("/api/caja/actual", headers=cajero["h"]).json()["arqueo"]
    assert arqueo["ventas_efectivo"] == 100 and arqueo["cobros_cambios_efectivo"] == 80
    assert arqueo["efectivo_esperado"] == 280


def test_cambio_por_producto_mas_barato_emite_nota_de_credito(client, datos, extra, sesion):
    cajero = sesion("cajero@a.com")
    orden = vender(client, cajero["h"], datos)["orden_id"]
    [r] = enviar(client, cajero, cambio(cajero, datos, [{"variante_id": extra["barata"], "cantidad": 1,
                                                         "precio_unitario": 60}], diferencia=-40, orden_id=orden))
    assert r["estado"] == "CONFIRMADA", r
    nota = r["detalle"]["nota_credito"]
    assert nota["codigo"].startswith("NC-") and nota["monto"] == 40


def test_cambios_offline_invalidos_se_rechazan_sin_tocar_el_stock(client, datos, extra, sesion):
    cajero = sesion("cajero@a.com")
    a = datos["a"]
    orden = vender(client, cajero["h"], datos)["orden_id"]
    talla_l = [{"variante_id": extra["talla_l"], "cantidad": 1, "precio_unitario": 100}]
    vieja, _ = orden_directa(datos, dias_atras=40)
    ajena, _ = orden_directa(datos, clave="b")

    casos = [
        (cambio(cajero, datos, talla_l, diferencia=15, orden_id=orden), "no coincide"),
        (cambio(cajero, datos, [{"variante_id": extra["cara"], "cantidad": 1, "precio_unitario": 180}],
                diferencia=80, orden_id=orden), "efectivo"),
        (cambio(cajero, datos, talla_l, orden_id=orden,
                devueltos=[{"variante_id": a["variante"], "cantidad": 2}]), "elegibles"),
        (cambio(cajero, datos, talla_l, orden_id=orden, inspeccion="NO_APTA"), "defecto"),
        (cambio(cajero, datos, talla_l, orden_id=vieja), "Fuera de plazo"),
        (cambio(cajero, datos, talla_l, orden_id=ajena), "Venta no encontrada"),
        (cambio(cajero, datos, talla_l), "orden_id o venta_uuid"),
        (cambio(cajero, datos, talla_l, venta_uuid=str(uuid4())), "Venta no encontrada"),
        (cambio(cajero, datos, talla_l, orden_id=orden, creado_en="2026-01-01T10:00:00Z"), "anterior a la venta"),
    ]
    resultados = enviar(client, cajero, *[op for op, _ in casos])
    for (op, texto), r in zip(casos, resultados):
        assert r["estado"] == "RECHAZADA" and texto in r["mensaje"], (texto, r)
    assert resultados[0]["detalle"]["diferencia_calculada"] == 0
    assert stock(extra["talla_l"], a["sucursal"])[0] == 5 and stock(a["variante"], a["sucursal"])[0] == 9

    # Un cliente no puede registrar cambios offline
    cliente = sesion("cliente@a.com")
    [r] = enviar(client, cliente, cambio(cliente, datos, talla_l, orden_id=orden))
    assert r["estado"] == "RECHAZADA" and "personal" in r["mensaje"]


def test_cambio_sin_stock_queda_en_conflicto_y_se_reintenta_al_reponer(client, datos, extra, sesion):
    cajero, admin = sesion("cajero@a.com"), sesion("admin@a.com")
    a = datos["a"]
    orden = vender(client, cajero["h"], datos)["orden_id"]
    _fijar_stock(extra["talla_l"], a["sucursal"], 0)
    op = cambio(cajero, datos, [{"variante_id": extra["talla_l"], "cantidad": 1, "precio_unitario": 100}], orden_id=orden)
    [r] = enviar(client, cajero, op)
    assert r["estado"] == "CONFLICTO" and r["detalle"]["items"][0]["disponible"] == 0
    assert stock(a["variante"], a["sucursal"])[0] == 9               # la devuelta tampoco ingresó

    [c] = client.get("/api/sync/conflictos", headers=admin["h"]).json()
    assert c["tipo"] == "CAMBIO" and c["items"][0]["talla"] == "L" and c["items"][0]["stock_actual"] == 0
    url = f"/api/sync/conflictos/{op['uuid']}/resolver"
    assert client.post(url, json={"accion": "AJUSTAR"}, headers=admin["h"]).status_code == 409

    _fijar_stock(extra["talla_l"], a["sucursal"], 2)
    r = client.post(url, json={"accion": "AJUSTAR"}, headers=admin["h"])
    assert r.status_code == 200 and r.json()["estado"] == "CONFIRMADA", r.text
    assert r.json()["detalle"]["codigo"].startswith("DEV-")
    assert stock(extra["talla_l"], a["sucursal"])[0] == 1 and stock(a["variante"], a["sucursal"])[0] == 10
    [e] = client.post("/api/sync/estado", json={"uuids": [op["uuid"]]}, headers=cajero["h"]).json()["resultados"]
    assert e["estado"] == "CONFIRMADA"


def test_catalogo_offline_trae_ventas_recientes_y_politica_solo_al_personal(client, datos, extra, sesion):
    cajero = sesion("cajero@a.com")
    orden = vender(client, cajero["h"], datos)["orden_id"]
    vieja, _ = orden_directa(datos, dias_atras=40)
    cat = client.get("/api/sync/catalogo", headers=cajero["h"]).json()
    assert cat["politica_devoluciones"]["plazo_cambio_dias"] == 30
    ids = [v["orden_id"] for v in cat["ventas_recientes"]]
    assert orden in ids and vieja not in ids
    v = next(v for v in cat["ventas_recientes"] if v["orden_id"] == orden)
    item = v["items"][0]
    assert item["variante_id"] == datos["a"]["variante"] and item["devuelto"] == 0 and item["retornable"]

    otra = client.get("/api/sync/catalogo", headers=sesion("cajero@b.com")["h"]).json()
    assert all(x["orden_id"] != orden for x in otra["ventas_recientes"])
    cliente = client.get("/api/sync/catalogo", headers=sesion("cliente@a.com")["h"]).json()
    assert "ventas_recientes" not in cliente and "politica_devoluciones" not in cliente
