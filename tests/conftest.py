from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def customer() -> pd.Series:
    return pd.Series({
        "cliente_id": "CLI_TEST", "tipo_cliente": "postpago", "antiguedad_meses": 24,
        "tiene_movil": True, "tiene_hogar": True, "oferta_hogar_id": "OF005",
        "tiene_internet_hogar": True, "es_movistar_total": False, "elegible_mt": True,
        "plan_actual_id": "OF002", "monto_facturado_prom": 120.0, "edad_rango": "36-45",
        "ubicacion_departamento": "Lima", "es_usuario_app": True,
        "consumo_datos_gb_prom": 35.0, "consumo_voz_min_prom": 100.0,
        "consumo_sms_prom": 2.0, "uso_app_movistar_prom": 5.0,
        "monto_facturado_prom_6m": 118.0, "dias_mora_prom": 0.0, "meses_moroso": 0,
        "n_reclamos": 0, "n_actividad_canal": 4, "canal_mas_usado": "Digital",
    })


@pytest.fixture
def catalog() -> pd.DataFrame:
    return pd.DataFrame([
        {"oferta_id": "OF001", "nombre_oferta": "Móvil 10", "tipo_oferta": "plan_movil", "segmento_objetivo": "movil", "es_movistar_total": False, "precio_mensual": 40.0, "ahorro_pct": 0, "gb_incluidos": 10, "cluster_hogar": None, "descripcion_bundle": None, "descripcion_corta": "Móvil 10"},
        {"oferta_id": "OF002", "nombre_oferta": "Móvil 25", "tipo_oferta": "plan_movil", "segmento_objetivo": "movil", "es_movistar_total": False, "precio_mensual": 60.0, "ahorro_pct": 0, "gb_incluidos": 25, "cluster_hogar": None, "descripcion_bundle": None, "descripcion_corta": "Móvil 25"},
        {"oferta_id": "OF005", "nombre_oferta": "Internet", "tipo_oferta": "plan_hogar", "segmento_objetivo": "hogar", "es_movistar_total": False, "precio_mensual": 90.0, "ahorro_pct": 0, "gb_incluidos": 0, "cluster_hogar": "mono", "descripcion_bundle": "Internet", "descripcion_corta": "Internet"},
        {"oferta_id": "OF008", "nombre_oferta": "Internet TV", "tipo_oferta": "plan_hogar", "segmento_objetivo": "hogar", "es_movistar_total": False, "precio_mensual": 130.0, "ahorro_pct": 0, "gb_incluidos": 0, "cluster_hogar": "duo", "descripcion_bundle": "Internet + TV", "descripcion_corta": "Internet TV"},
        {"oferta_id": "OF011", "nombre_oferta": "Upgrade móvil", "tipo_oferta": "upgrade", "segmento_objetivo": "movil", "es_movistar_total": False, "precio_mensual": 20.0, "ahorro_pct": 0, "gb_incluidos": 15, "cluster_hogar": None, "descripcion_bundle": None, "descripcion_corta": "Upgrade"},
        {"oferta_id": "OF013", "nombre_oferta": "Upgrade hogar", "tipo_oferta": "upgrade", "segmento_objetivo": "hogar", "es_movistar_total": False, "precio_mensual": 25.0, "ahorro_pct": 0, "gb_incluidos": 0, "cluster_hogar": None, "descripcion_bundle": None, "descripcion_corta": "Upgrade hogar"},
        {"oferta_id": "OF016", "nombre_oferta": "Router", "tipo_oferta": "equipo", "segmento_objetivo": "hogar", "es_movistar_total": False, "precio_mensual": 15.0, "ahorro_pct": 0, "gb_incluidos": 0, "cluster_hogar": None, "descripcion_bundle": None, "descripcion_corta": "Router"},
        {"oferta_id": "OF017", "nombre_oferta": "Streaming", "tipo_oferta": "paquete_adicional", "segmento_objetivo": "ambos", "es_movistar_total": False, "precio_mensual": 20.0, "ahorro_pct": 0, "gb_incluidos": 0, "cluster_hogar": None, "descripcion_bundle": None, "descripcion_corta": "Streaming"},
        {"oferta_id": "OF019", "nombre_oferta": "Roaming", "tipo_oferta": "paquete_adicional", "segmento_objetivo": "movil", "es_movistar_total": False, "precio_mensual": 30.0, "ahorro_pct": 0, "gb_incluidos": 5, "cluster_hogar": None, "descripcion_bundle": None, "descripcion_corta": "Roaming"},
        {"oferta_id": "OF020", "nombre_oferta": "MT", "tipo_oferta": "movistar_total", "segmento_objetivo": "ambos", "es_movistar_total": True, "precio_mensual": 150.0, "ahorro_pct": 20, "gb_incluidos": 30, "cluster_hogar": None, "descripcion_bundle": None, "descripcion_corta": "MT"},
    ])

