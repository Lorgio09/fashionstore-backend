"""
Posventa: devoluciones y cambios (CU-01 a CU-11), notas de crédito (CU-07) y caja (CU-20).
"""
from datetime import datetime, timedelta

import pytest

from app.db.database import SessionLocal
from app.db.tenant import set_global
from app.models.inventario import Categoria, DetalleOrden, Inventario, Orden, Prenda, Sucursal, VariantePrenda
from app.models.usuarios import Usuario

D = "/api/devoluciones"


@pytest.fixture()
def extra(datos):
    """Empresa A: otra talla del mismo modelo, un producto más barato, uno más caro y una segunda sucursal."""
    db = SessionLocal()
    set_global(db)
    a = datos["a"]
    eid = a["empresa"]
    norte = Sucursal(nombre="Norte A", empresa_id=eid)
    db.add(norte)
    db.flush()
    talla_l = VariantePrenda(prenda_id=a["prenda"], talla="L", color="Negro", codigo_sku="SKU-L", empresa_id=eid)
    barata = Prenda(nombre="Gorra A", precio_base=60, categoria_id=a["categoria"], proveedor_id=a["proveedor"], empresa_id=eid)
    cara = Prenda(nombre="Chamarra A", precio_base=180, categoria_id=a["categoria"], proveedor_id=a["proveedor"], empresa_id=eid)
    db.add_all([talla_l, barata, cara])
    db.flush()
    v_barata = VariantePrenda(prenda_id=barata.id, talla="U", color="Azul", codigo_sku="SKU-G", empresa_id=eid)
    v_cara = VariantePrenda(prenda_id=cara.id, talla="M", color="Gris", codigo_sku="SKU-C", empresa_id=eid)
    db.add_all([v_barata, v_cara])
    db.flush()
    for v, suc, stock in ((talla_l, a["sucursal"], 5), (v_barata, a["sucursal"], 5), (v_cara, a["sucursal"], 5),
                          (talla_l, norte.id, 3)):
        db.add(Inventario(variante_id=v.id, sucursal_id=suc, stock_disponible=stock, stock_reservado=0, empresa_id=eid))
    ids = {"norte": norte.id, "talla_l": talla_l.id, "barata": v_barata.id, "cara": v_cara.id}
    db.commit()
    db.close()
    return ids


def vender(client, h, datos, cantidad=1, metodo="EFECTIVO", nota=None, variante=None):
    a = datos["a"]
    cuerpo = {"sucursal_id": a["sucursal"], "metodo_pago": metodo, "total": 100 * cantidad,
              "items": [{"prenda_id": a["prenda"], "variante_id": variante or a["variante"], "cantidad": cantidad, "precio": 100}]}
    if nota:
        cuerpo["nota_credito"] = nota
    r = client.post("/api/catalogo/checkout/presencial", json=cuerpo, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def linea(client, h, orden_id):
    [venta] = client.get(f"{D}/ventas?orden_id={orden_id}", headers=h).json()
    return venta["items"][0]["detalle_orden_id"]


def solicitar(client, h, orden_id, detalle, cantidad=1, motivo="TALLA", resolucion="CAMBIO_VARIANTE", **extra):
    return client.post(f"{D}/solicitudes", json={"orden_id": orden_id, "motivo": motivo, "resolucion": resolucion,
                                                 "items": [{"detalle_orden_id": detalle, "cantidad": cantidad}], **extra},
                       headers=h)


def stock(variante_id, sucursal_id):
    db = SessionLocal()
    set_global(db)
    inv = db.query(Inventario).filter(Inventario.variante_id == variante_id, Inventario.sucursal_id == sucursal_id).one()
    db.close()
    return inv.stock_disponible, inv.stock_no_disponible


def orden_directa(datos, clave="a", dias_atras=0, cliente_email=None, canal="PRESENCIAL"):
    """Crea una venta pagada con fecha en el pasado (para probar plazos y compras en línea)."""
    db = SessionLocal()
    set_global(db)
    e = datos[clave]
    cliente = db.query(Usuario).filter(Usuario.email == cliente_email).one() if cliente_email else None
    o = Orden(empresa_id=e["empresa"], fecha_orden=datetime.utcnow() - timedelta(days=dias_atras), canal=canal,
              sucursal_id=None if canal == "WEB" else e["sucursal"], estado="PAGADO" if canal == "WEB" else "COMPLETADO",
              metodo_pago="STRIPE" if canal == "WEB" else "EFECTIVO", total=100, nombre_cliente="x",
              cliente_id=cliente.id if cliente else None)
    o.detalles.append(DetalleOrden(prenda_id=e["prenda"], variante_id=e["variante"], cantidad=1, precio_unitario=100))
    db.add(o)
    db.commit()
    ids = (o.id, o.detalles[0].id)
    db.close()
    return ids


# ---------- CU-01, CU-03, CU-04, CU-10 ----------
def test_cambio_de_talla_completo(client, datos, extra, token):
    cajero, admin = token("cajero@a.com"), token("admin@a.com")
    orden = vender(client, cajero, datos, cantidad=2)["orden_id"]
    r = solicitar(client, cajero, orden, linea(client, cajero, orden))
    assert r.status_code == 201, r.text
    sol = r.json()
    assert sol["codigo"].startswith("DEV-") and sol["estado"] == "EN_INSPECCION" and sol["acciones"] == []
    url = f"{D}/solicitudes/{sol['codigo']}"

    assert client.post(f"{url}/inspeccionar", json={"resultado": "APTA"}, headers=cajero).status_code == 403
    assert client.post(f"{url}/cambio-variante", json={"items": [{"detalle_id": sol["items"][0]["id"], "variante_id": extra["talla_l"]}]},
                       headers=cajero).status_code == 409   # todavía no inspeccionada
    r = client.post(f"{url}/inspeccionar", json={"resultado": "APTA"}, headers=admin).json()
    assert r["estado"] == "INSPECCIONADA" and "CAMBIO_VARIANTE" in r["acciones"]

    r = client.post(f"{url}/cambio-variante", json={"items": [{"detalle_id": sol["items"][0]["id"], "variante_id": extra["talla_l"]}]},
                    headers=cajero)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "CAMBIO_REALIZADO" and r.json()["items"][0]["entregado"]["talla"] == "L"
    assert stock(datos["a"]["variante"], datos["a"]["sucursal"])[0] == 9   # 10 - 2 vendidas + 1 devuelta apta
    assert stock(extra["talla_l"], datos["a"]["sucursal"])[0] == 4         # 5 - 1 entregada
    venta = client.get(f"{D}/ventas?orden_id={orden}", headers=cajero).json()[0]
    assert venta["items"][0]["elegible"] == 1 and venta["items"][0]["cambios_realizados"] == 1


def test_reembolso_de_prenda_no_apta_no_vuelve_al_stock_vendible(client, datos, extra, token):
    cajero, admin = token("cajero@a.com"), token("admin@a.com")
    orden = vender(client, cajero, datos)["orden_id"]
    sol = solicitar(client, cajero, orden, linea(client, cajero, orden), motivo="DEFECTO", resolucion="REEMBOLSO").json()
    url = f"{D}/solicitudes/{sol['codigo']}"
    client.post(f"{url}/inspeccionar", json={"resultado": "NO_APTA", "observacion": "Costura rota"}, headers=admin)
    r = client.post(f"{url}/reembolso", json={"forma": "MEDIO_ORIGINAL"}, headers=cajero).json()
    assert r["estado"] == "REEMBOLSADA" and r["monto_reembolsado"] == 100
    assert r["forma_reembolso"] == "EFECTIVO"   # la venta fue en efectivo
    assert stock(datos["a"]["variante"], datos["a"]["sucursal"]) == (9, 1)


def test_rechazo_en_inspeccion_exige_motivo(client, datos, extra, token):
    cajero, admin = token("cajero@a.com"), token("admin@a.com")
    orden = vender(client, cajero, datos)["orden_id"]
    sol = solicitar(client, cajero, orden, linea(client, cajero, orden)).json()
    url = f"{D}/solicitudes/{sol['codigo']}/inspeccionar"
    assert client.post(url, json={"resultado": "RECHAZAR"}, headers=admin).status_code == 422
    r = client.post(url, json={"resultado": "RECHAZAR", "observacion": "No es la prenda vendida"}, headers=admin).json()
    assert r["estado"] == "RECHAZADA"
    # Rechazada no consume unidades: se puede volver a solicitar
    assert solicitar(client, cajero, orden, linea(client, cajero, orden)).status_code == 201


# ---------- Validaciones de la solicitud (CU-01 flujos alternos, CU-09) ----------
def test_validaciones_de_la_solicitud(client, datos, extra, token):
    cajero, admin = token("cajero@a.com"), token("admin@a.com")
    orden = vender(client, cajero, datos)["orden_id"]
    det = linea(client, cajero, orden)
    assert solicitar(client, cajero, orden, det, cantidad=2).status_code == 409          # más de lo vendido
    orden_b, det_b = orden_directa(datos, "b")
    r = solicitar(client, admin, orden_b, det_b, sucursal_id=datos["a"]["sucursal"])
    assert r.status_code == 404 and r.json()["detail"] == "Venta no encontrada"           # otra empresa

    vieja, det_vieja = orden_directa(datos, dias_atras=40)
    r = solicitar(client, cajero, vieja, det_vieja)
    assert r.status_code == 409 and "Fuera de plazo" in r.json()["detail"]
    assert solicitar(client, cajero, vieja, det_vieja, motivo="DEFECTO").status_code == 201   # garantía de 90 días

    politica = {"plazo_cambio_dias": 30, "plazo_garantia_dias": 90, "categorias_no_retornables": [datos["a"]["categoria"]],
                "max_cambios_por_prenda": 2, "max_devoluciones_mes_cliente": 3}
    assert client.put(f"{D}/politica", json=politica, headers=cajero).status_code == 403
    assert client.put(f"{D}/politica", json=politica, headers=admin).status_code == 200
    r = solicitar(client, cajero, orden, det)
    assert r.status_code == 409 and "no retornable" in r.json()["detail"]
    assert solicitar(client, cajero, orden, det, motivo="DEFECTO").status_code == 201


def test_recargo_por_demora_si_la_politica_lo_permite(client, datos, extra, token):
    admin, cajero = token("admin@a.com"), token("cajero@a.com")
    client.put(f"{D}/politica", json={"plazo_cambio_dias": 30, "plazo_garantia_dias": 90, "max_cambios_por_prenda": 2,
                                      "max_devoluciones_mes_cliente": 3, "fuera_de_plazo": "RECARGO", "recargo_pct": 10},
               headers=admin)
    vieja, det = orden_directa(datos, dias_atras=40)
    sol = solicitar(client, cajero, vieja, det, resolucion="REEMBOLSO").json()
    assert sol["fuera_de_plazo"] and sol["recargo"] == 10 and sol["monto_a_favor"] == 90


# ---------- CU-05 y CU-07: cambio por otro producto y notas de crédito ----------
def test_cambio_por_producto_mas_barato_genera_nota_y_se_usa_en_una_venta(client, datos, extra, token):
    cajero, admin = token("cajero@a.com"), token("admin@a.com")
    orden = vender(client, cajero, datos)["orden_id"]
    sol = solicitar(client, cajero, orden, linea(client, cajero, orden), resolucion="CAMBIO_PRODUCTO").json()
    url = f"{D}/solicitudes/{sol['codigo']}"
    client.post(f"{url}/inspeccionar", json={"resultado": "APTA"}, headers=admin)
    r = client.post(f"{url}/cambio-producto", json={"items": [{"variante_id": extra["barata"], "cantidad": 1}]}, headers=cajero).json()
    assert r["estado"] == "CAMBIO_REALIZADO" and r["nota_credito"]["monto"] == 40
    codigo = r["nota_credito"]["codigo"]
    assert stock(extra["barata"], datos["a"]["sucursal"])[0] == 4

    venta = vender(client, cajero, datos, nota=codigo)
    assert venta["pagado_con_nota_credito"] == 40 and venta["a_pagar"] == 60
    nota = client.get(f"{D}/notas-credito/{codigo}", headers=cajero).json()
    assert nota["estado"] == "USADA" and [m["tipo"] for m in nota["movimientos"]] == ["EMISION", "APLICACION"]
    r = client.post("/api/catalogo/checkout/presencial", json={
        "sucursal_id": datos["a"]["sucursal"], "metodo_pago": "EFECTIVO", "total": 100, "nota_credito": codigo,
        "items": [{"prenda_id": datos["a"]["prenda"], "variante_id": datos["a"]["variante"], "cantidad": 1, "precio": 100}]},
        headers=cajero)
    assert r.status_code == 409 and "usada" in r.json()["detail"]


def test_cambio_por_producto_mas_caro_cobra_la_diferencia(client, datos, extra, token):
    cajero, admin = token("cajero@a.com"), token("admin@a.com")
    orden = vender(client, cajero, datos)["orden_id"]
    sol = solicitar(client, cajero, orden, linea(client, cajero, orden), resolucion="CAMBIO_PRODUCTO").json()
    url = f"{D}/solicitudes/{sol['codigo']}"
    client.post(f"{url}/inspeccionar", json={"resultado": "APTA"}, headers=admin)
    destino = {"items": [{"variante_id": extra["cara"], "cantidad": 1}]}
    assert client.post(f"{url}/cambio-producto", json=destino, headers=cajero).status_code == 422
    r = client.post(f"{url}/cambio-producto", json={**destino, "forma_cobro": "EFECTIVO"}, headers=cajero).json()
    assert r["monto_cobrado"] == 80 and r["forma_cobro"] == "EFECTIVO" and r["nota_credito"] is None


# ---------- CU-08: cambio sin stock ----------
def test_cambio_sin_stock_espera_y_luego_se_completa(client, datos, extra, token):
    cajero, admin = token("cajero@a.com"), token("admin@a.com")
    db = SessionLocal()
    set_global(db)
    db.query(Inventario).filter(Inventario.variante_id == extra["talla_l"], Inventario.sucursal_id == datos["a"]["sucursal"]) \
        .update({"stock_disponible": 0})
    db.commit()
    db.close()
    orden = vender(client, cajero, datos)["orden_id"]
    sol = solicitar(client, cajero, orden, linea(client, cajero, orden)).json()
    url = f"{D}/solicitudes/{sol['codigo']}"
    client.post(f"{url}/inspeccionar", json={"resultado": "APTA"}, headers=admin)
    cambio = {"items": [{"detalle_id": sol["items"][0]["id"], "variante_id": extra["talla_l"]}]}
    r = client.post(f"{url}/cambio-variante", json=cambio, headers=cajero)
    assert r.status_code == 409 and "Sin stock" in r.json()["detail"]

    disp = client.get(f"{D}/disponibilidad/{extra['talla_l']}", headers=cajero).json()
    assert {(d["sucursal"], d["talla"], d["stock"]) for d in disp["en_sucursales"]} >= {("Norte A", "L", 3)}

    r = client.post(f"{url}/sin-stock", json={"decision": "ESPERAR_STOCK"}, headers=cajero).json()
    assert r["estado"] == "PENDIENTE_STOCK"
    assert stock(datos["a"]["variante"], datos["a"]["sucursal"])[0] == 10   # la devuelta ya ingresó (10 - 1 + 1)
    db = SessionLocal()
    set_global(db)
    db.query(Inventario).filter(Inventario.variante_id == extra["talla_l"], Inventario.sucursal_id == datos["a"]["sucursal"]) \
        .update({"stock_disponible": 2})
    db.commit()
    db.close()
    r = client.post(f"{url}/cambio-variante", json=cambio, headers=cajero).json()
    assert r["estado"] == "CAMBIO_REALIZADO"
    assert stock(datos["a"]["variante"], datos["a"]["sucursal"])[0] == 10   # no se ingresa dos veces


# ---------- CU-02: cliente en línea y autorización por máximo mensual ----------
def test_cliente_solicita_en_linea_y_el_maximo_mensual_requiere_autorizacion(client, datos, extra, token):
    cliente, admin = token("cliente@a.com"), token("admin@a.com")
    client.put(f"{D}/politica", json={"plazo_cambio_dias": 30, "plazo_garantia_dias": 90, "max_cambios_por_prenda": 2,
                                      "max_devoluciones_mes_cliente": 1}, headers=admin)
    web1, det1 = orden_directa(datos, cliente_email="cliente@a.com", canal="WEB")
    web2, det2 = orden_directa(datos, cliente_email="cliente@a.com", canal="WEB")
    compras = client.get(f"{D}/mis-compras", headers=cliente).json()
    assert {c["orden_id"] for c in compras} == {web1, web2}

    ajena = vender(client, token("cajero@a.com"), datos)["orden_id"]
    r = solicitar(client, cliente, ajena, 1, sucursal_id=datos["a"]["sucursal"])
    assert r.status_code == 404 and r.json()["detail"] == "Compra no encontrada"

    s1 = solicitar(client, cliente, web1, det1, resolucion="REEMBOLSO", sucursal_id=datos["a"]["sucursal"]).json()
    assert s1["canal"] == "EN_LINEA" and not s1["requiere_autorizacion"]
    s2 = solicitar(client, cliente, web2, det2, resolucion="REEMBOLSO", sucursal_id=datos["a"]["sucursal"]).json()
    assert s2["requiere_autorizacion"] and not s2["autorizada"]
    url = f"{D}/solicitudes/{s2['codigo']}"
    assert client.post(f"{url}/inspeccionar", json={"resultado": "APTA"}, headers=admin).status_code == 409
    assert client.post(f"{url}/autorizar", headers=admin).json()["autorizada"]
    client.post(f"{url}/inspeccionar", json={"resultado": "APTA"}, headers=admin)
    r = client.post(f"{url}/reembolso", json={"forma": "MEDIO_ORIGINAL"}, headers=admin).json()
    assert r["reembolso_pendiente_procesador"] and r["forma_reembolso"] == "MEDIO_ORIGINAL"   # pagó con Stripe
    assert [s["codigo"] for s in client.get(f"{D}/solicitudes", headers=cliente).json()["solicitudes"]] == [s2["codigo"], s1["codigo"]]


# ---------- Aislamiento y CU-11 ----------
def test_otra_empresa_no_ve_las_solicitudes_y_el_historial_tiene_indicadores(client, datos, extra, token):
    cajero, admin = token("cajero@a.com"), token("admin@a.com")
    orden = vender(client, cajero, datos)["orden_id"]
    sol = solicitar(client, cajero, orden, linea(client, cajero, orden), motivo="COLOR", resolucion="REEMBOLSO").json()
    client.post(f"{D}/solicitudes/{sol['codigo']}/inspeccionar", json={"resultado": "APTA"}, headers=admin)
    client.post(f"{D}/solicitudes/{sol['codigo']}/reembolso", json={"forma": "EFECTIVO"}, headers=cajero)

    admin_b = token("admin@b.com")
    assert client.get(f"{D}/solicitudes/{sol['codigo']}", headers=admin_b).status_code == 404
    assert client.get(f"{D}/solicitudes", headers=admin_b).json()["totales"]["solicitudes"] == 0

    h = client.get(f"{D}/solicitudes?motivo=color", headers=admin).json()
    assert h["totales"]["solicitudes"] == 1 and h["totales"]["monto_reembolsado"] == 100
    hoy = datetime.utcnow().date().isoformat()
    rep = client.post("/api/ia/reportes/ejecutar", json={"intencion": {"tipo": "devoluciones_por_motivo",
                                                                       "fecha_desde": "2026-01-01", "fecha_hasta": hoy}},
                      headers=admin).json()["reporte"]
    assert rep["filas"][0]["motivo"] == "Cambio de color" and rep["totales"]["solicitudes"] == 1


# ---------- CU-20: caja ----------
def test_caja_abre_acumula_y_cierra_sin_diferencia(client, datos, extra, token):
    cajero, admin = token("cajero@a.com"), token("admin@a.com")
    r = client.post("/api/caja/abrir", json={"fondo_inicial": 100}, headers=cajero)
    assert r.status_code == 201, r.text
    assert client.post("/api/caja/abrir", json={"fondo_inicial": 50}, headers=cajero).status_code == 409

    vender(client, cajero, datos, cantidad=2)                  # 200 en efectivo
    vender(client, cajero, datos, metodo="QR")                 # 100 por QR (no es efectivo)
    orden = vender(client, cajero, datos)["orden_id"]          # 100 en efectivo, luego se reembolsa
    sol = solicitar(client, cajero, orden, linea(client, cajero, orden), resolucion="REEMBOLSO").json()
    client.post(f"{D}/solicitudes/{sol['codigo']}/inspeccionar", json={"resultado": "APTA"}, headers=admin)
    client.post(f"{D}/solicitudes/{sol['codigo']}/reembolso", json={"forma": "EFECTIVO"}, headers=cajero)

    arqueo = client.get("/api/caja/actual", headers=cajero).json()["arqueo"]
    assert arqueo["ventas_efectivo"] == 300 and arqueo["reembolsos_efectivo"] == 100
    assert arqueo["efectivo_esperado"] == 300   # 100 de fondo + 300 de ventas - 100 de reembolso
    r = client.post("/api/caja/cerrar", json={"efectivo_contado": 300, "pendientes_locales": {"cantidad": 2, "monto_efectivo": 150}},
                    headers=cajero).json()
    assert r["estado"] == "CERRADA" and r["diferencia"] == 0 and r["pendientes_locales"]["cantidad"] == 2
    assert client.post("/api/caja/abrir", json={"fondo_inicial": 100}, headers=cajero).status_code == 201


def test_caja_con_diferencia_exige_observacion_y_autorizacion(client, datos, extra, token):
    cajero, admin = token("cajero@a.com"), token("admin@a.com")
    client.post("/api/caja/abrir", json={"fondo_inicial": 100}, headers=cajero)
    assert client.post("/api/caja/cerrar", json={"efectivo_contado": 0}, headers=cajero).status_code == 422
    r = client.post("/api/caja/cerrar", json={"efectivo_contado": 0, "observacion": "Faltante"}, headers=cajero).json()
    assert r["estado"] == "PENDIENTE_AUTORIZACION" and r["diferencia"] == -100   # supera el umbral de 50
    assert client.post(f"/api/caja/{r['id']}/autorizar", headers=cajero).status_code == 403
    assert client.post(f"/api/caja/{r['id']}/autorizar", headers=admin).json()["estado"] == "CERRADA"
    assert client.post("/api/caja/abrir", json={"fondo_inicial": 10}, headers=admin).status_code == 422   # sin sucursal
    assert client.get("/api/caja/turnos", headers=token("admin@b.com")).json() == []
