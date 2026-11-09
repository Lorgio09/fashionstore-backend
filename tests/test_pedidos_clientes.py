"""Pedidos de los clientes web y móvil: reservas con datos legibles y correo duplicado = 409."""


def test_reservas_del_cliente_traen_prenda_y_sucursal(client, datos, token):
    h = token("cliente@a.com")
    reserva = {"fecha_visita": "2026-12-01T10:00:00", "sucursal_id": datos["a"]["sucursal"],
               "detalles": [{"variante_id": datos["a"]["variante"], "cantidad": 2}]}
    creada = client.post("/api/reservas/", json=reserva, headers=h)
    assert creada.status_code == 200, creada.text
    yo = client.post("/api/usuarios/login", json={"email": "cliente@a.com", "password": "Clave123!"}).json()["usuario"]
    lista = client.get(f"/api/reservas/cliente/{yo['id']}", headers=h).json()
    assert len(lista) == 1
    r = lista[0]
    assert r["sucursal_nombre"] == "Sucursal a" and r["sucursal_id"] == datos["a"]["sucursal"]
    d = r["detalles"][0]
    assert d == {**d, "variante_id": datos["a"]["variante"], "cantidad": 2, "prenda_id": datos["a"]["prenda"],
                 "prenda_nombre": "Prenda a", "talla": "M", "color": "Negro", "precio": 100}


def test_registro_con_correo_duplicado_responde_409(client):
    cuerpo = {"nombre_completo": "Repetido", "email": "cliente@a.com", "password": "Clave123!"}
    r = client.post("/api/usuarios/registro/cliente", json=cuerpo)
    assert r.status_code == 409 and r.json()["detail"] == "El correo ya está registrado"
