"""
Sincronización offline (contrato API §6): idempotencia (RNF05), conflictos de stock (RN21),
transacciones por operación (RNF04), aislamiento entre empresas (RN03) y registro (RNF10).
"""
from uuid import uuid4

import pytest

CLAVE = "Clave123!"


@pytest.fixture()
def sesion(client):
    cache = {}

    def _sesion(email: str) -> dict:
        if email not in cache:
            r = client.post("/api/usuarios/login", json={"email": email, "password": CLAVE})
            assert r.status_code == 200, r.text
            j = r.json()
            cache[email] = {"h": {"Authorization": f"Bearer {j['access_token']}"}, "id": j["usuario"]["id"],
                            "empresa": (j["empresa"] or {}).get("id")}  # la plataforma no tiene empresa
        return cache[email]

    return _sesion


def venta(s, datos, clave="a", cantidad=1, precio=100.0, **cambios):
    op = {
        "uuid": str(uuid4()), "tipo": "VENTA", "empresa_id": s["empresa"], "sucursal_id": datos[clave]["sucursal"],
        "usuario_id": s["id"], "creado_en": "2026-11-03T14:05:00-04:00",
        "datos": {
            "metodo_pago": "EFECTIVO", "nombre_cliente": "Cliente ocasional", "total": cantidad * precio,
            "items": [{"variante_id": datos[clave]["variante"], "cantidad": cantidad, "precio_unitario": precio}],
        },
    }
    op.update(cambios)
    return op


def reserva(s, datos, cliente_id=None, cantidad=1):
    return {
        "uuid": str(uuid4()), "tipo": "RESERVA", "empresa_id": s["empresa"], "sucursal_id": datos["a"]["sucursal"],
        "usuario_id": s["id"], "creado_en": "2026-11-03T15:00:00-04:00",
        "datos": {"cliente_id": cliente_id, "fecha_visita": "2026-11-05T10:00:00",
                  "items": [{"variante_id": datos["a"]["variante"], "cantidad": cantidad}]},
    }


def enviar(client, s, *ops):
    r = client.post("/api/sync/operaciones", json={"dispositivo_id": "pc-caja-1", "operaciones": list(ops)},
                    headers=s["h"])
    assert r.status_code == 200, r.text
    assert r.json()["procesadas"] == len(ops)
    return r.json()["resultados"]


def stock(client, s, clave_variante):
    inventario = client.get("/api/sync/catalogo", headers=s["h"]).json()["inventario"]
    return next(i["stock_disponible"] for i in inventario if i["variante_id"] == clave_variante)


# ---------- Preparar dispositivo ----------
def test_catalogo_offline_del_cajero_solo_trae_su_sucursal_y_los_clientes(client, datos, sesion):
    admin = sesion("admin@a.com")
    assert client.post("/api/empresa/sucursales", json={"nombre": "Segunda A"}, headers=admin["h"]).status_code == 201

    c = client.get("/api/sync/catalogo", headers=sesion("cajero@a.com")["h"]).json()
    assert c["empresa"]["slug"] == "empresa-a" and c["vigencia_horas"] == 24
    assert c["usuario"]["rol_nombre"] == "Cajero"
    assert [s["id"] for s in c["sucursales"]] == [datos["a"]["sucursal"]]
    assert [p["nombre"] for p in c["prendas"]] == ["Prenda a"]
    assert c["prendas"][0]["variantes"][0]["id"] == datos["a"]["variante"]
    assert c["inventario"] == [{"variante_id": datos["a"]["variante"], "sucursal_id": datos["a"]["sucursal"],
                                "stock_disponible": 10}]
    assert [x["email"] for x in c["clientes"]] == ["cliente@a.com"]

    # El administrador ve todas las sucursales activas
    assert len(client.get("/api/sync/catalogo", headers=admin["h"]).json()["sucursales"]) == 2


def test_catalogo_offline_del_cliente_no_incluye_otros_clientes(client, datos, sesion):
    c = client.get("/api/sync/catalogo", headers=sesion("cliente@a.com")["h"]).json()
    assert c["clientes"] == [] and len(c["sucursales"]) == 1


# ---------- Ventas offline ----------
def test_venta_offline_confirmada_descuenta_stock_y_queda_como_offline(client, datos, sesion):
    cajero = sesion("cajero@a.com")
    [r] = enviar(client, cajero, venta(cajero, datos, cantidad=2))
    assert r["estado"] == "CONFIRMADA" and r["servidor_id"] and r["duplicada"] is False
    assert stock(client, cajero, datos["a"]["variante"]) == 8

    orden = client.get("/api/catalogo/ordenes/historial", headers=cajero["h"]).json()[0]
    assert orden["id"] == r["servidor_id"]
    assert orden["canal"] == "OFFLINE" and orden["metodo_pago"] == "EFECTIVO"
    assert orden["sucursal_id"] == datos["a"]["sucursal"] and orden["usuario_id"] == cajero["id"]


def test_reenviar_la_misma_operacion_no_la_duplica(client, datos, sesion):
    cajero = sesion("cajero@a.com")
    op = venta(cajero, datos)
    [primera] = enviar(client, cajero, op)
    [segunda] = enviar(client, cajero, op)  # p. ej. se cortó la red antes de recibir la respuesta
    assert segunda["duplicada"] is True
    assert segunda["estado"] == primera["estado"] == "CONFIRMADA"
    assert segunda["servidor_id"] == primera["servidor_id"]
    assert stock(client, cajero, datos["a"]["variante"]) == 9

    # El mismo uuid repetido dentro de un lote tampoco duplica
    otra = venta(cajero, datos)
    r1, r2 = enviar(client, cajero, otra, otra)
    assert r1["duplicada"] is False and r2["duplicada"] is True and r1["servidor_id"] == r2["servidor_id"]
    assert stock(client, cajero, datos["a"]["variante"]) == 8
    assert len(client.get("/api/catalogo/ordenes/historial", headers=cajero["h"]).json()) == 2


def test_conflicto_de_stock_no_descuenta_ni_afecta_al_resto_del_lote(client, datos, sesion):
    cajero = sesion("cajero@a.com")
    sin_stock, normal = venta(cajero, datos, cantidad=11), venta(cajero, datos, cantidad=3)
    r_conflicto, r_ok = enviar(client, cajero, sin_stock, normal)
    assert r_conflicto["estado"] == "CONFLICTO" and r_conflicto["servidor_id"] is None
    assert r_conflicto["detalle"] == {"items": [{"variante_id": datos["a"]["variante"], "solicitado": 11,
                                                 "disponible": 10}]}
    assert r_ok["estado"] == "CONFIRMADA"
    assert stock(client, cajero, datos["a"]["variante"]) == 7  # nunca negativo


def test_operaciones_invalidas_se_rechazan_sin_tocar_el_stock(client, datos, sesion):
    cajero, admin = sesion("cajero@a.com"), sesion("admin@a.com")
    base = lambda **c: venta(cajero, datos, **c)  # noqa: E731
    malas = {
        "otra empresa": base(empresa_id=datos["b"]["empresa"]),
        "otro usuario": base(usuario_id=admin["id"]),
        "sucursal de B": base(sucursal_id=datos["b"]["sucursal"]),
        "tipo desconocido": base(tipo="DEVOLUCION"),
    }
    op = base()
    op["datos"]["metodo_pago"] = "QR"
    malas["pago con QR"] = op
    op = base()
    op["datos"]["total"] = 1
    malas["total alterado"] = op
    op = base()
    op["datos"]["items"][0]["variante_id"] = datos["b"]["variante"]
    malas["variante de B"] = op
    op = base()
    op["datos"]["items"][0]["cantidad"] = 0
    op["datos"]["total"] = 0
    malas["cantidad cero"] = op
    op = base()
    op["datos"] = {"metodo_pago": "EFECTIVO"}
    malas["datos incompletos"] = op

    resultados = enviar(client, cajero, *malas.values())
    for motivo, r in zip(malas, resultados):
        assert r["estado"] == "RECHAZADA", motivo
        assert r["servidor_id"] is None and r["mensaje"], motivo
    assert stock(client, cajero, datos["a"]["variante"]) == 10
    assert client.get("/api/catalogo/ordenes/historial", headers=cajero["h"]).json() == []

    # Un rechazo es final: reenviarlo devuelve lo mismo
    [r] = enviar(client, cajero, malas["pago con QR"])
    assert r["estado"] == "RECHAZADA" and r["duplicada"] is True


def test_el_cajero_solo_opera_en_su_sucursal(client, datos, sesion):
    admin, cajero = sesion("admin@a.com"), sesion("cajero@a.com")
    otra = client.post("/api/empresa/sucursales", json={"nombre": "Segunda A"}, headers=admin["h"]).json()
    [r] = enviar(client, cajero, venta(cajero, datos, sucursal_id=otra["id"]))
    assert r["estado"] == "RECHAZADA" and "sucursal asignada" in r["mensaje"]


def test_lote_de_mas_de_50_operaciones_se_rechaza_completo(client, datos, sesion):
    cajero = sesion("cajero@a.com")
    ops = [venta(cajero, datos) for _ in range(51)]
    r = client.post("/api/sync/operaciones", json={"operaciones": ops}, headers=cajero["h"])
    assert r.status_code == 422


# ---------- Reservas offline ----------
def test_cliente_reserva_offline_para_si_mismo_pero_no_puede_vender(client, datos, sesion):
    cliente = sesion("cliente@a.com")
    r_venta, r_reserva = enviar(client, cliente, venta(cliente, datos), reserva(cliente, datos, cliente_id=99999))
    assert r_venta["estado"] == "RECHAZADA"
    assert r_reserva["estado"] == "CONFIRMADA"
    reservas = client.get(f"/api/reservas/cliente/{cliente['id']}", headers=cliente["h"]).json()
    assert [x["id"] for x in reservas] == [r_reserva["servidor_id"]]
    assert stock(client, cliente, datos["a"]["variante"]) == 9


def test_reserva_offline_del_personal_exige_un_cliente_de_la_empresa(client, datos, sesion):
    cajero, cliente = sesion("cajero@a.com"), sesion("cliente@a.com")
    sin_cliente, cliente_ajeno, ok = (reserva(cajero, datos), reserva(cajero, datos, cliente_id=99999),
                                      reserva(cajero, datos, cliente_id=cliente["id"], cantidad=2))
    r1, r2, r3 = enviar(client, cajero, sin_cliente, cliente_ajeno, ok)
    assert r1["estado"] == "RECHAZADA" and "cliente" in r1["mensaje"]
    assert r2["estado"] == "RECHAZADA"
    assert r3["estado"] == "CONFIRMADA"
    assert stock(client, cajero, datos["a"]["variante"]) == 8


# ---------- Estado y aislamiento ----------
def test_consultar_estado_de_operaciones(client, datos, sesion):
    cajero = sesion("cajero@a.com")
    op = venta(cajero, datos)
    enviar(client, cajero, op)
    desconocida = str(uuid4())

    def estados(s):
        r = client.post("/api/sync/estado", json={"uuids": [op["uuid"], desconocida]}, headers=s["h"])
        assert r.status_code == 200
        return [x["estado"] for x in r.json()["resultados"]]

    assert estados(cajero) == ["CONFIRMADA", "DESCONOCIDA"]
    assert estados(sesion("admin@a.com")) == ["CONFIRMADA", "DESCONOCIDA"]
    assert estados(sesion("cliente@a.com")) == ["DESCONOCIDA", "DESCONOCIDA"]  # no es suya
    assert estados(sesion("admin@b.com")) == ["DESCONOCIDA", "DESCONOCIDA"]    # otra empresa


def test_uuid_de_otra_empresa_no_se_reutiliza_ni_se_revela(client, datos, sesion):
    cajero_a, cajero_b = sesion("cajero@a.com"), sesion("cajero@b.com")
    op_a = venta(cajero_a, datos)
    enviar(client, cajero_a, op_a)
    op_b = venta(cajero_b, datos, clave="b", uuid=op_a["uuid"])
    [r] = enviar(client, cajero_b, op_b)
    assert r["estado"] == "RECHAZADA" and r["duplicada"] is False and r["servidor_id"] is None
    assert stock(client, cajero_b, datos["b"]["variante"]) == 10


def test_con_suscripcion_suspendida_la_operacion_espera_y_no_se_pierde(client, datos, sesion):
    plataforma, cajero = sesion("plataforma@test.com"), sesion("cajero@b.com")
    url = f"/api/plataforma/empresas/{datos['b']['empresa']}/suscripcion/estado"
    op = venta(cajero, datos, clave="b")

    assert client.patch(url, json={"estado": "SUSPENDIDA"}, headers=plataforma["h"]).status_code == 200
    r = client.post("/api/sync/operaciones", json={"operaciones": [op]}, headers=cajero["h"])
    assert r.status_code == 403  # el lote no se procesa: el dispositivo la conserva en LOCAL
    assert client.get("/api/sync/catalogo", headers=cajero["h"]).status_code == 403

    assert client.patch(url, json={"estado": "ACTIVA"}, headers=plataforma["h"]).status_code == 200
    [r] = enviar(client, cajero, op)
    assert r["estado"] == "CONFIRMADA" and r["duplicada"] is False


# ---------- Conflictos ----------
def _crear_conflicto(client, datos, sesion, cantidad=11):
    cajero = sesion("cajero@a.com")
    op = venta(cajero, datos, cantidad=cantidad)
    [r] = enviar(client, cajero, op)
    assert r["estado"] == "CONFLICTO"
    return op


def test_solo_gestion_de_la_empresa_ve_los_conflictos(client, datos, sesion):
    op = _crear_conflicto(client, datos, sesion)
    assert client.get("/api/sync/conflictos", headers=sesion("cajero@a.com")["h"]).status_code == 403
    assert client.get("/api/sync/conflictos", headers=sesion("admin@b.com")["h"]).json() == []

    [c] = client.get("/api/sync/conflictos", headers=sesion("admin@a.com")["h"]).json()
    assert c["uuid"] == op["uuid"] and c["tipo"] == "VENTA"
    assert c["usuario"]["id"] == sesion("cajero@a.com")["id"]
    assert c["items"][0]["prenda"] == "Prenda a" and c["items"][0]["cantidad"] == 11
    assert c["items"][0]["stock_actual"] == 10


def test_resolver_conflicto_rechazandolo(client, datos, sesion):
    op = _crear_conflicto(client, datos, sesion)
    admin, cajero = sesion("admin@a.com"), sesion("cajero@a.com")
    url = f"/api/sync/conflictos/{op['uuid']}/resolver"

    assert client.post(url, json={"accion": "RECHAZAR"}, headers=admin["h"]).status_code == 422
    assert client.post(url, json={"accion": "RECHAZAR", "motivo": "x"}, headers=sesion("admin@b.com")["h"]).status_code == 404
    r = client.post(url, json={"accion": "RECHAZAR", "motivo": "Se devolvió el dinero al cliente"}, headers=admin["h"])
    assert r.status_code == 200 and r.json()["estado"] == "RECHAZADA"

    # El dispositivo se entera al consultar el estado
    [e] = client.post("/api/sync/estado", json={"uuids": [op["uuid"]]}, headers=cajero["h"]).json()["resultados"]
    assert e["estado"] == "RECHAZADA" and "devolvió el dinero" in e["mensaje"]
    assert client.post(url, json={"accion": "RECHAZAR", "motivo": "otra vez"}, headers=admin["h"]).status_code == 409
    assert stock(client, cajero, datos["a"]["variante"]) == 10


def test_resolver_conflicto_ajustando_cantidades(client, datos, sesion):
    op = _crear_conflicto(client, datos, sesion)
    admin, cajero = sesion("admin@a.com"), sesion("cajero@a.com")
    url = f"/api/sync/conflictos/{op['uuid']}/resolver"
    variante = datos["a"]["variante"]

    r = client.post(url, json={"accion": "AJUSTAR", "items": [{"variante_id": variante, "cantidad": 11}]},
                    headers=admin["h"])
    assert r.status_code == 409 and "no alcanza" in r.json()["detail"]
    r = client.post(url, json={"accion": "AJUSTAR", "items": [{"variante_id": datos["b"]["variante"], "cantidad": 1}]},
                    headers=admin["h"])
    assert r.status_code == 422
    assert stock(client, cajero, variante) == 10  # los intentos fallidos no tocan el stock

    r = client.post(url, json={"accion": "AJUSTAR", "items": [{"variante_id": variante, "cantidad": 10}]},
                    headers=admin["h"])
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "CONFIRMADA" and r.json()["servidor_id"]
    assert stock(client, cajero, variante) == 0

    orden = client.get("/api/catalogo/ordenes/historial", headers=admin["h"]).json()[0]
    assert orden["total"] == 1000 and orden["usuario_id"] == cajero["id"]  # responsable: quien vendió
    assert client.get("/api/sync/conflictos", headers=admin["h"]).json() == []


# ---------- Registro (RNF10) ----------
def test_registro_de_sincronizacion_solo_para_el_administrador(client, datos, sesion):
    cajero, admin = sesion("cajero@a.com"), sesion("admin@a.com")
    enviar(client, cajero, venta(cajero, datos), venta(cajero, datos, cantidad=50))
    assert client.get("/api/sync/registro", headers=cajero["h"]).status_code == 403

    registro = client.get("/api/sync/registro", headers=admin["h"]).json()
    assert sorted(x["estado"] for x in registro) == ["CONFIRMADA", "CONFLICTO"]
    assert all(x["dispositivo_id"] == "pc-caja-1" for x in registro)
    conflictos = client.get("/api/sync/registro?estado=conflicto", headers=admin["h"]).json()
    assert len(conflictos) == 1
    assert client.get("/api/sync/registro", headers=sesion("admin@b.com")["h"]).json() == []
