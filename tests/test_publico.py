"""Cara pública de la plataforma: directorio de tiendas y planes (sin token)."""


def test_directorio_de_tiendas_solo_activas_y_con_datos_publicos(client, datos, token):
    tiendas = client.get("/api/publico/tiendas").json()
    assert [t["slug"] for t in tiendas] == ["empresa-a", "empresa-b"]
    a = tiendas[0]
    assert a == {**a, "nombre": "Empresa A", "sucursales": 1, "prendas": 1, "categorias": ["Categoria a"]}
    assert "nit" not in a and "id" not in a

    # Una empresa suspendida desaparece del directorio
    empresa_b = datos["b"]["empresa"]
    r = client.patch(f"/api/plataforma/empresas/{empresa_b}/estado", json={"estado": "SUSPENDIDA"},
                     headers=token("plataforma@test.com"))
    assert r.status_code == 200, r.text
    assert [t["slug"] for t in client.get("/api/publico/tiendas").json()] == ["empresa-a"]
    assert client.get("/api/publico/tiendas/empresa-b").status_code == 404


def test_tienda_sin_sucursales_activas_no_aparece_en_el_directorio(client, datos, token):
    r = client.patch(f"/api/empresa/sucursales/{datos['a']['sucursal']}/estado", json={"activa": False},
                     headers=token("admin@a.com"))
    assert r.status_code == 200, r.text
    assert [t["slug"] for t in client.get("/api/publico/tiendas").json()] == ["empresa-b"]


def test_detalle_de_tienda_y_planes(client, datos):
    t = client.get("/api/publico/tiendas/EMPRESA-A").json()
    assert t["nombre"] == "Empresa A" and t["lista_sucursales"][0]["nombre"] == "Sucursal a"
    assert client.get("/api/publico/tiendas/no-existe").status_code == 404
    planes = client.get("/api/publico/planes").json()
    assert {p["codigo"] for p in planes} == {"BASICO", "PROFESIONAL"}
    assert next(p for p in planes if p["codigo"] == "PROFESIONAL")["permite_reportes_ia"] is True
