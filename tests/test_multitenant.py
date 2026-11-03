"""
Reglas críticas multitenant (RN02, RN03, RNF01, RNF02) y de planes (RN05–RN09).
"""


# ---------- Aislamiento entre empresas ----------
def test_catalogo_publico_muestra_solo_la_tienda_indicada(client, datos):
    a = client.get("/api/catalogo/", headers={"X-Empresa": "empresa-a"}).json()
    b = client.get("/api/catalogo/", headers={"X-Empresa": "empresa-b"}).json()
    assert [p["nombre"] for p in a] == ["Prenda a"]
    assert [p["nombre"] for p in b] == ["Prenda b"]


def test_el_token_manda_sobre_el_header(client, datos, token):
    """Un usuario de A no puede leer B cambiando el header X-Empresa."""
    r = client.get("/api/catalogo/", headers={**token("admin@a.com"), "X-Empresa": "empresa-b"})
    assert [p["nombre"] for p in r.json()] == ["Prenda a"]


def test_admin_a_no_puede_ver_modificar_ni_eliminar_prenda_de_b(client, datos, token):
    h = token("admin@a.com")
    prenda_b = datos["b"]["prenda"]
    assert client.get(f"/api/catalogo/{prenda_b}", headers=h).status_code == 404
    assert client.put(f"/api/catalogo/{prenda_b}", data={"nombre": "hackeada"}, headers=h).status_code == 404
    assert client.delete(f"/api/catalogo/{prenda_b}", headers=h).status_code == 404
    # La prenda de B sigue intacta
    r = client.get(f"/api/catalogo/{prenda_b}", headers=token("admin@b.com"))
    assert r.status_code == 200 and r.json()["nombre"] == "Prenda b"


def test_listar_usuarios_solo_de_la_empresa_y_sin_password(client, datos, token):
    r = client.get("/api/usuarios/", headers=token("admin@a.com"))
    assert r.status_code == 200
    emails = {u["email"] for u in r.json()}
    assert emails == {"admin@a.com", "cajero@a.com", "cliente@a.com"}
    assert all("password_hash" not in u for u in r.json())


def test_venta_en_sucursal_de_otra_empresa_es_rechazada(client, datos, token):
    venta = {
        "sucursal_id": datos["b"]["sucursal"], "metodo_pago": "EFECTIVO", "total": 100,
        "items": [{"prenda_id": datos["b"]["prenda"], "variante_id": datos["b"]["variante"], "cantidad": 1, "precio": 100}],
    }
    r = client.post("/api/catalogo/checkout/presencial", json=venta, headers=token("admin@a.com"))
    assert r.status_code == 404


def test_reserva_con_prenda_de_otra_empresa_es_rechazada(client, datos, token):
    reserva = {
        "fecha_visita": "2026-12-01T10:00:00", "sucursal_id": datos["a"]["sucursal"],
        "detalles": [{"variante_id": datos["b"]["variante"], "cantidad": 1}],
    }
    r = client.post("/api/reservas/", json=reserva, headers=token("cliente@a.com"))
    assert r.status_code == 404


def test_reservas_de_otra_sucursal_ajena_no_se_listan(client, datos, token):
    r = client.get(f"/api/reservas/sucursal/{datos['b']['sucursal']}", headers=token("cajero@a.com"))
    assert r.status_code == 200 and r.json() == []


def test_venta_presencial_registra_responsable_sucursal_y_descuenta_stock(client, datos, token):
    h = token("cajero@a.com")
    venta = {
        "sucursal_id": datos["a"]["sucursal"], "metodo_pago": "efectivo", "total": 200,
        "items": [{"prenda_id": datos["a"]["prenda"], "variante_id": datos["a"]["variante"], "cantidad": 2, "precio": 100}],
    }
    assert client.post("/api/catalogo/checkout/presencial", json=venta, headers=h).status_code == 200
    inventario = client.get(f"/api/catalogo/inventario/sucursal/{datos['a']['sucursal']}", headers=h).json()
    assert inventario[0]["stock"] == 8
    orden = client.get("/api/catalogo/ordenes/historial", headers=h).json()[0]
    assert orden["canal"] == "PRESENCIAL" and orden["metodo_pago"] == "EFECTIVO"
    assert orden["sucursal_id"] == datos["a"]["sucursal"] and orden["usuario_id"] is not None


def test_cliente_no_puede_usar_endpoints_de_gestion(client, datos, token):
    h = token("cliente@a.com")
    assert client.post("/api/catalogo/categorias", json={"nombre": "x"}, headers=h).status_code == 403
    assert client.get("/api/auditoria/", headers=h).status_code == 403


# ---------- Planes y suscripciones ----------
def test_plan_basico_limita_sucursales_activas(client, datos, token):
    h = token("admin@b.com")  # B: plan Básico, ya tiene 1 sucursal
    assert client.post("/api/empresa/sucursales", json={"nombre": "Segunda"}, headers=h).status_code == 201
    r = client.post("/api/empresa/sucursales", json={"nombre": "Tercera"}, headers=h)
    assert r.status_code == 409 and "hasta 2" in r.json()["detail"]


def test_reactivar_sucursal_respeta_el_limite(client, datos, token):
    h = token("admin@b.com")
    segunda = client.post("/api/empresa/sucursales", json={"nombre": "Segunda"}, headers=h).json()
    client.patch(f"/api/empresa/sucursales/{segunda['id']}/estado", json={"activa": False}, headers=h)
    assert client.post("/api/empresa/sucursales", json={"nombre": "Tercera"}, headers=h).status_code == 201
    r = client.patch(f"/api/empresa/sucursales/{segunda['id']}/estado", json={"activa": True}, headers=h)
    assert r.status_code == 409


def test_reportes_ia_bloqueados_en_plan_basico(client, datos, token):
    r = client.post("/api/ia/generar-reporte", json={"texto_voz": "ventas del mes"}, headers=token("admin@b.com"))
    assert r.status_code == 403 and "Profesional" in r.json()["detail"]


def test_mi_empresa_informa_plan_uso_y_funciones(client, datos, token):
    b = client.get("/api/empresa/mi-empresa", headers=token("cajero@b.com")).json()
    assert b["suscripcion"]["plan"]["codigo"] == "BASICO"
    assert b["suscripcion"]["funciones"] == {"reportes_ia": False, "offline": True}
    a = client.get("/api/empresa/mi-empresa", headers=token("cajero@a.com")).json()
    assert a["suscripcion"]["funciones"]["reportes_ia"] is True


def test_suscripcion_suspendida_permite_solo_consultar(client, datos, token):
    p = token("plataforma@test.com")
    r = client.patch(f"/api/plataforma/empresas/{datos['b']['empresa']}/suscripcion/estado",
                     json={"estado": "SUSPENDIDA"}, headers=p)
    assert r.status_code == 200
    h = token("admin@b.com")
    assert client.get("/api/auditoria/", headers=h).status_code == 200
    assert client.post("/api/catalogo/categorias", json={"nombre": "Nueva"}, headers=h).status_code == 403


def test_empresa_suspendida_no_puede_iniciar_sesion(client, datos, token):
    p = token("plataforma@test.com")
    client.patch(f"/api/plataforma/empresas/{datos['b']['empresa']}/estado", json={"estado": "SUSPENDIDA"}, headers=p)
    r = client.post("/api/usuarios/login", json={"email": "admin@b.com", "password": "Clave123!"})
    assert r.status_code == 403


def test_downgrade_bloqueado_si_supera_el_limite(client, datos, token):
    h = token("admin@a.com")  # A: Profesional
    for nombre in ("A2", "A3"):
        assert client.post("/api/empresa/sucursales", json={"nombre": nombre}, headers=h).status_code == 201
    r = client.post(f"/api/plataforma/empresas/{datos['a']['empresa']}/suscripcion",
                    json={"plan_codigo": "BASICO"}, headers=token("plataforma@test.com"))
    assert r.status_code == 409 and "desactivar 1" in r.json()["detail"]


# ---------- Administración de la plataforma ----------
def test_solo_la_plataforma_registra_empresas(client, datos, token):
    nueva = {
        "razon_social": "Empresa C", "nit": "NIT-c", "slug": "empresa-c", "plan_codigo": "BASICO",
        "admin_nombre": "Admin C", "admin_email": "admin@c.com", "admin_password": "Clave123!",
    }
    assert client.post("/api/plataforma/empresas", json=nueva, headers=token("admin@a.com")).status_code == 403
    r = client.post("/api/plataforma/empresas", json=nueva, headers=token("plataforma@test.com"))
    assert r.status_code == 201, r.text
    assert r.json()["suscripcion"]["plan"]["codigo"] == "BASICO"
    # El nuevo administrador entra a una empresa vacía
    h = token("admin@c.com")
    assert client.get("/api/catalogo/", headers=h).json() == []
    assert client.get("/api/usuarios/", headers=h).json()[0]["email"] == "admin@c.com"


def test_nit_y_slug_duplicados_se_rechazan(client, datos, token):
    dup = {
        "razon_social": "Copia", "nit": "NIT-a", "slug": "otra", "plan_codigo": "BASICO",
        "admin_nombre": "Admin Copia", "admin_email": "copia@x.com", "admin_password": "Clave123!",
    }
    p = token("plataforma@test.com")
    r = client.post("/api/plataforma/empresas", json=dup, headers=p)
    assert r.status_code == 409 and "NIT" in r.json()["detail"]
    r = client.post("/api/plataforma/empresas", json={**dup, "nit": "NIT-nuevo", "slug": "empresa-b"}, headers=p)
    assert r.status_code == 409 and "slug" in r.json()["detail"]
