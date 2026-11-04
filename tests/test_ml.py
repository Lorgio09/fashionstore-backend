"""
Módulo de analítica inteligente con Machine Learning (examen 8.4 y 8.5).

Los datos sintéticos se generan una sola vez para este archivo (empresa A, plan Profesional) con una
fecha fija, así los resultados son reproducibles. Se verifica que:
- el modelo supervisado le gana al método simple y la validación es temporal;
- el no supervisado recupera los perfiles con los que se generaron los clientes;
- los modelos son por empresa, el alcance por rol se respeta y todo se integra con los reportes.
"""
from datetime import date, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sklearn.metrics import adjusted_rand_score

from main import app
from app.db.database import Base, SessionLocal, engine
from app.db.tenant import set_global
from app.ml import datos_sinteticos as sinteticos
from app.models.ml import ModeloML
from app.models.usuarios import ROL_ENCARGADO, Rol, Usuario
from app.services.reportes import catalogo, interprete
from tests.conftest import CLAVE, _HASH, _sembrar

HOY = date(2026, 11, 4)


@pytest.fixture(scope="module")
def ml():
    parche = pytest.MonkeyPatch()
    parche.setattr(catalogo, "hoy_local", lambda: HOY)
    parche.setattr(interprete, "hoy_local", lambda: HOY)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    datos = _sembrar()
    db = SessionLocal()
    set_global(db)
    eid = datos["a"]["empresa"]
    sucursales, prendas = sinteticos.crear_catalogo(db, eid)
    clientes = sinteticos.crear_clientes(db, eid, _HASH)
    admin = db.query(Usuario).filter(Usuario.email == "admin@a.com").one()
    sinteticos.generar_ventas(db, eid, sucursales, prendas, clientes, {s.id: admin.id for s in sucursales},
                              hasta=HOY - timedelta(days=1))
    rol = db.query(Rol).filter(Rol.nombre == ROL_ENCARGADO).one()
    db.add(Usuario(email="encargado@a.com", nombre_completo="Encargado A", password_hash=_HASH, rol_id=rol.id,
                   empresa_id=eid, sucursal_id=sucursales[0].id))
    ids = [s.id for s in sucursales]
    db.commit()
    db.close()
    with TestClient(app) as cliente:
        tokens = {}

        def token(email):
            if email not in tokens:
                r = cliente.post("/api/usuarios/login", json={"email": email, "password": CLAVE})
                assert r.status_code == 200, r.text
                tokens[email] = {"Authorization": f"Bearer {r.json()['access_token']}"}
            return tokens[email]

        yield {"c": cliente, "token": token, "datos": datos, "sucursales": ids}
    parche.undo()


# ---------- Entrenamiento, evaluación y validación (8.4 puntos 2, 3, 4 y 5) ----------
def test_entrenar_evalua_y_valida_ambos_modelos(ml):
    c, h = ml["c"], ml["token"]("admin@a.com")
    r = c.post("/api/ml/entrenar", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()["demanda"]["metricas"]
    # Supervisado: validación temporal y mejor que el método simple
    assert d["prueba"]["mae"] < d["prueba"]["mae_metodo_simple"]
    assert d["prueba"]["mejora_vs_simple_pct"] > 0 and d["prueba"]["error_total_pct"] < 15
    assert len(d["validacion_cruzada"]["pliegues"]) == 3 and d["validacion_cruzada"]["mejora_promedio_pct"] > 0
    assert d["importancias"][0]["variable"] == "Promedio de los últimos 28 días"
    assert r.json()["demanda"]["parametros"]["variables_descartadas"]
    # No supervisado: elige k por silueta y recupera los perfiles sintéticos
    s = r.json()["segmentacion"]["metricas"]
    assert s["k"] == 3 and s["silueta"] > 0.4 and s["ari_perfiles_sinteticos"] > 0.8
    assert {g["segmento"] for g in s["segmentos"]} == {"Frecuentes", "Premium", "Ocasionales"}

    # Reentrenar crea una versión nueva y deja una sola activa por tipo
    c.post("/api/ml/entrenar", headers=h)
    modelos = c.get("/api/ml/modelos", headers=h).json()
    assert sorted((m["tipo"], m["version"]) for m in modelos) == [("DEMANDA", 2), ("SEGMENTACION", 2)]
    assert all("artefacto" not in m for m in modelos)


# ---------- Integración con el sistema (8.4 punto 6) ----------
def test_prediccion_de_demanda_con_rango_y_cobertura(ml):
    c, h = ml["c"], ml["token"]("admin@a.com")
    r = c.get("/api/ml/demanda?dias=7", headers=h)
    assert r.status_code == 200, r.text
    p = r.json()
    assert len(p["diario"]) == 7 and p["filas"]
    for f in p["filas"]:
        assert f["minimo"] <= f["unidades"] <= f["maximo"]
        assert f["alerta"] in {"CRÍTICO", "ATENCIÓN", "OK", "—"}
        if f["sucursal_id"] is None:
            assert f["stock"] is None and f["alerta"] == "—"   # la web no tiene stock propio
    alertas = c.get("/api/ml/reposicion", headers=h).json()
    assert alertas and all(a["cobertura_dias"] < 14 for a in alertas)


def test_segmentos_recuperan_los_perfiles_programados(ml):
    c, h = ml["c"], ml["token"]("admin@a.com")
    r = c.get("/api/ml/segmentos", headers=h).json()
    asignados = [(sinteticos.perfil_sintetico(x["email"]), x["segmento"]) for x in r["clientes"]]
    asignados = [a for a in asignados if a[0]]
    assert len(asignados) == 50
    assert adjusted_rand_score(*zip(*asignados)) > 0.8
    premium = next(s for s in r["segmentos"] if s["segmento"] == "Premium")
    assert premium["ticket_promedio"] > max(s["ticket_promedio"] for s in r["segmentos"] if s["segmento"] != "Premium")
    assert premium["accion_sugerida"]


def test_sin_modelo_activo_se_entrena_automaticamente(ml):
    db = SessionLocal()
    set_global(db)
    db.query(ModeloML).update({"activo": False})
    db.commit()
    db.close()
    c, h = ml["c"], ml["token"]("admin@a.com")
    assert c.get("/api/ml/segmentos", headers=h).status_code == 200
    assert {m["tipo"] for m in c.get("/api/ml/modelos", headers=h).json()} == {"DEMANDA", "SEGMENTACION"}


# ---------- Dashboard analítico (8.4 puntos 8 y 9) ----------
def test_dashboard_analitico(ml):
    c, h = ml["c"], ml["token"]("admin@a.com")
    d = c.get("/api/ml/dashboard", headers=h).json()
    assert set(d["indicadores"]) == {"ventas_mes", "cantidad_ventas_mes", "ticket_promedio", "unidades_mes",
                                     "clientes_activos_30_dias"}
    reales = [p for p in d["serie"] if p["real"] is not None]
    futuras = [p for p in d["serie"] if p["prediccion"] is not None]
    assert len(reales) == 60 and len(futuras) == 14 and futuras[0]["fecha"] == HOY.isoformat()
    assert len(d["segmentos"]) == 3 and d["alertas_reposicion"]
    assert d["modelos"]["demanda"]["metricas"]["importancias"] and not d["avisos"]


# ---------- Seguridad y alcance (8.4, RN03) ----------
def test_encargado_ve_solo_su_sucursal_y_no_entrena(ml):
    c, h = ml["c"], ml["token"]("encargado@a.com")
    filas = c.get("/api/ml/demanda", headers=h).json()["filas"]
    assert {f["sucursal_id"] for f in filas} == {ml["sucursales"][0]}
    assert c.post("/api/ml/entrenar", headers=h).status_code == 403
    assert c.get("/api/ml/dashboard", headers=ml["token"]("cajero@a.com")).status_code == 403


def test_cada_empresa_entrena_solo_con_sus_datos(ml):
    c, token = ml["c"], ml["token"]
    assert c.get("/api/ml/dashboard", headers=token("admin@b.com")).status_code == 403   # plan Básico
    r = c.post(f"/api/plataforma/empresas/{ml['datos']['b']['empresa']}/suscripcion",
               json={"plan_codigo": "PROFESIONAL"}, headers=token("plataforma@test.com"))
    assert r.status_code in (200, 201), r.text
    r = c.post("/api/ml/entrenar", headers=token("admin@b.com"))
    assert r.status_code == 409 and "ventas" in r.json()["detail"]   # no usa los datos ni modelos de A
    d = c.get("/api/ml/dashboard", headers=token("admin@b.com")).json()
    assert d["avisos"] and d["segmentos"] == []


# ---------- Reportes inteligentes (8.4 punto 7, 8.5) ----------
@pytest.mark.parametrize("texto, tipo", [
    ("¿Cuánto voy a vender la próxima semana?", "prediccion_demanda"),
    ("¿Qué categorías se van a quedar sin stock?", "prediccion_demanda"),
    ("Mostrame los segmentos de clientes", "segmentos_clientes"),
    ("¿Qué tan precisos son los modelos?", "evaluacion_modelos"),
])
def test_reportes_inteligentes_en_lenguaje_natural(ml, texto, tipo):
    c, h = ml["c"], ml["token"]("admin@a.com")
    r = c.post("/api/ia/reportes", json={"texto": texto}, headers=h).json()
    assert r["estado"] == "OK" and r["intencion"]["tipo"] == tipo, r
    assert r["reporte"]["filas"] and r["narrativa"]
    if tipo == "prediccion_demanda":
        assert r["intencion"]["fecha_desde"] == (HOY + timedelta(days=1)).isoformat()
        assert r["intencion"]["fecha_hasta"] == (HOY + timedelta(days=7)).isoformat()


def test_reportes_inteligentes_se_exportan(ml):
    from openpyxl import load_workbook

    c, h = ml["c"], ml["token"]("admin@a.com")
    for intencion in ({"tipo": "prediccion_demanda"}, {"tipo": "segmentos_clientes"}, {"tipo": "evaluacion_modelos"}):
        pdf = c.post("/api/ia/reportes/exportar", json={"intencion": intencion, "formato": "pdf"}, headers=h)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF"), pdf.text
        xlsx = c.post("/api/ia/reportes/exportar", json={"intencion": intencion, "formato": "xlsx"}, headers=h)
        assert load_workbook(BytesIO(xlsx.content)).active["A2"].value == catalogo.TIPOS[intencion["tipo"]].nombre
