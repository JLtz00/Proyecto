from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from nbo.advisor_ui import (
    AdvisorContext, alternative_rows, confidence_summary, label_objective, label_stage,
    money, percentage, service_summary,
)


def test_advisor_labels_and_formats_are_human_readable():
    assert percentage(.326) == "33%"
    assert money(89.9) == "S/ 89.90"
    assert label_stage("elegible_mt") == "Elegible para Movistar Total"
    assert label_objective("completar_hogar_para_mt") == "Completar hogar para habilitar MT"
    assert confidence_summary({"level": "medio", "relevant_support": 8}) == (
        "Confianza Medio · 8 observaciones relevantes"
    )


def test_advisor_context_prioritizes_operational_state():
    customer = {
        "tiene_movil": True, "tipo_cliente": "postpago", "tiene_hogar": False,
        "tiene_internet_hogar": False, "es_movistar_total": False,
    }
    state = {
        "state_version": 2, "attributes": {"tiene_hogar": True, "tiene_internet_hogar": True},
    }
    assert service_summary(customer, state) == ["Móvil postpago", "Internet hogar"]
    context = AdvisorContext(
        result={
            "decision_id": "d1", "cliente": {"cliente_id": "CLI1"},
            "recommendation": {"oferta_id": "OF005"}, "state_version": 1,
        },
        state=state,
        events=[],
    )
    assert context.cliente_id == "CLI1"
    assert context.offer_id == "OF005"
    assert context.state_version == 2


def test_alternatives_are_reduced_to_actionable_columns():
    rows = alternative_rows([{
        "nombre_oferta": "Plan hogar", "canal": "Digital", "precio_mensual": 89.9,
        "probabilidad_venta": .4, "explanation": {"positive": ["Completa la ruta MT"]},
    }])
    assert rows == [{
        "Oferta": "Plan hogar", "Canal": "Digital", "Precio": "S/ 89.90",
        "Venta estimada": "40%", "Motivo principal": "Completa la ruta MT",
    }]


def test_streamlit_dashboard_empty_state_renders_without_errors():
    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py").run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "Siguiente mejor conversación"
    assert app.button[0].label == "Consultar cliente"


def test_reference_cases_are_present_and_local_mode_is_default():
    app = AppTest.from_file(Path(__file__).parents[1] / "streamlit_app.py").run(timeout=30)
    labels = [button.label for button in app.button]
    assert "CLI000001  ·  Completar hogar" in labels
    assert "CLI000013  ·  Elegible MT" in labels
    assert "CLI000018  ·  Cliente MT" in labels
    origin = next(radio for radio in app.radio if radio.label == "Origen")
    assert origin.value == "Motor local"
