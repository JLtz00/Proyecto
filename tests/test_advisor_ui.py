from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest
import yaml

from nbo.advisor_app import create_app
from nbo.advisor_local import LocalAdvisorApi
from nbo.advisor_ui import (
    AdvisorContext, advisor_confidence, advisor_fit_level, advisor_level, advisor_next_step,
    alternative_rows,
    confidence_summary, label_moment, label_objective, label_stage, money, percentage,
    service_summary,
)
from nbo.config import load_config
from nbo.engine import NBOEngine
from nbo.schemas import CustomerEventRequest


def test_advisor_labels_and_formats_are_human_readable():
    assert percentage(.326) == "33%"
    assert money(89.9) == "S/ 89.90"
    assert label_stage("elegible_mt") == "Elegible para Movistar Total"
    assert label_objective("completar_hogar_para_mt") == "Completar sus servicios del hogar"
    assert "8 observaciones relevantes" in confidence_summary({"level": "medio", "relevant_support": 8})
    assert advisor_level(.82) == "Alta" and advisor_level(.42) == "Media"
    assert advisor_fit_level(.51) == "Muy buen ajuste"
    assert advisor_confidence({"level": "bajo"}) == "Pocos datos: confirma la necesidad con el cliente"
    assert advisor_next_step(
        {"objective": "convertir_a_mt"}, "Movistar Total Max",
    ) == "Presenta Movistar Total Max y explica cómo reúne sus servicios."
    assert label_moment("proximo_contacto_asesor") == "En el próximo contacto"


def test_advisor_context_prioritizes_operational_state():
    customer = {
        "tiene_movil": True, "tipo_cliente": "postpago", "tiene_hogar": False,
        "tiene_internet_hogar": False, "es_movistar_total": False,
    }
    state = {
        "state_version": 2, "attributes": {"tiene_hogar": True, "tiene_internet_hogar": True},
    }
    services = service_summary(customer, state)
    assert len(services) == 2 and "Internet hogar" in services
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
    assert rows[0]["Precio"] == "S/ 89.90"
    assert rows[0]["Oportunidad"] == "Media (40%)"


@pytest.fixture(scope="module")
def advisor_backend(tmp_path_factory):
    root = tmp_path_factory.mktemp("advisor")
    config = load_config()
    project_root = Path(__file__).parents[1]
    config["project"]["data_dir"] = str(project_root / "dataset")
    config["project"]["artifact_dir"] = str(project_root / "artifacts")
    config["project"]["database_path"] = str(root / "advisor.sqlite3")
    config_path = root / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return LocalAdvisorApi(NBOEngine(str(config_path), persist=True))


@pytest.fixture
def flask_app(advisor_backend):
    return create_app({"TESTING": True, "WTF_CSRF_ENABLED": False}, advisor_backend)


def _decision_id(html: bytes) -> str:
    match = re.search(r'data-decision-id="([0-9a-f-]{36})"', html.decode())
    assert match
    return match.group(1)


def test_flask_empty_search_health_and_local_assets(flask_app):
    client = flask_app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert "La próxima conversación" in response.text
    assert "Listo para consultar" in response.text
    assert 'aria-live="polite"' in response.text
    assert "https://" not in response.text and "cdn" not in response.text.lower()
    assert '"historyEnabled":false' in response.text
    assert client.get("/health").json["api_version"] == "1.5.0"
    assert client.get("/static/vendor/htmx.min.js").status_code == 200
    assert client.get("/static/icons.svg").status_code == 200
    assert client.get("/static/js/theme-init.js").status_code == 200
    assert client.get("/static/img/Logo_nbo_ui.png").status_code == 200
    assert client.get("/static/img/icon_nbo_ui.ico").status_code == 200
    assert 'class="brand-logo"' in response.text
    assert 'rel="icon"' in response.text
    assert 'data-theme-toggle' in response.text
    assert "#sun" in response.text and "#moon" in response.text
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp


def test_search_normalizes_and_renders_all_advisor_information(flask_app):
    client = flask_app.test_client()
    response = client.get(
        "/ui/clientes/cli000013/workspace", headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "<html" not in response.text
    for text in (
        "CLI000013", "Recomendación principal", "Ajuste con el cliente",
        "Facilidad para contactar", "Interés si responde", "Guion para conversar",
        "Por qué se recomienda", "Si no acepta", "Análisis completo",
        "Probabilidad de contacto", "Score interno de ranking", "Pago mensual promedio",
        "Uso de datos", "Cambios recientes", "Trazabilidad del ranking",
        "Versiones, estado y auditoría",
    ):
        assert text in response.text
    full = client.get("/ui/clientes/CLI000013/workspace")
    assert full.status_code == 200 and "<!doctype html>" in full.text.lower()


def test_read_only_advisor_keeps_search_and_hides_operational_controls(advisor_backend):
    app = create_app(
        {
            "TESTING": True,
            "ADVISOR_READ_ONLY": True,
            "JURY_MODE": False,
            "WTF_CSRF_ENABLED": False,
        },
        advisor_backend,
    )
    client = app.test_client()
    response = client.get(
        "/ui/clientes/CLI000001/workspace", headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "CLI000001" in response.text and "Recomendación principal" in response.text
    assert "Resultado de la conversación" not in response.text
    assert "Cambios recientes" not in response.text
    assert client.get("/jury").status_code == 404
    assert client.post("/ui/clientes/CLI000001/recalcular").status_code == 405


def test_missing_customer_and_engine_failure_are_html_errors(flask_app):
    missing = flask_app.test_client().get(
        "/ui/clientes/NO-EXISTE/workspace", headers={"HX-Request": "true"},
    )
    assert missing.status_code == 404 and 'role="alert"' in missing.text
    unavailable = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False}, backend=None)
    unavailable.extensions["advisor_backend"] = None
    unavailable.config["ADVISOR_STARTUP_ERROR"] = "artefactos ausentes"
    response = unavailable.test_client().get(
        "/ui/clientes/CLI000001/workspace", headers={"HX-Request": "true"},
    )
    assert response.status_code == 503 and "artefactos ausentes" in response.text


def test_contact_is_idempotent_and_browser_fields_cannot_change_decision(flask_app, advisor_backend):
    client = flask_app.test_client()
    workspace = client.get("/ui/clientes/CLI000018/workspace", headers={"HX-Request": "true"})
    decision_id = _decision_id(workspace.data)
    url = f"/ui/decisiones/{decision_id}/contacto"
    first = client.post(url, headers={"HX-Request": "true"})
    second = client.post(url)
    assert first.status_code == second.status_code == 200
    assert "<html" not in first.text and "<!doctype html>" in second.text.lower()
    interaction = advisor_backend.store.get_decision_interaction(decision_id)
    assert {"displayed", "contacted"} <= interaction["funnel_events"]

    feedback = client.post(
        f"/ui/decisiones/{decision_id}/feedback",
        data={
            "resultado_final": "aceptada", "medio_probatorio": "chat_log",
            "cliente_id": "CLI000001", "oferta_id": "OF999", "canal": "Tienda",
        }, headers={"HX-Request": "true"},
    )
    assert feedback.status_code == 200 and "activación continúa pendiente" in feedback.text
    stored = advisor_backend.store.get_decision(decision_id)
    assert stored["cliente_id"] == "CLI000018" and stored["top_offer_id"] != "OF999"


def test_acceptance_does_not_activate_then_activation_recalculates_and_replays(flask_app, advisor_backend):
    client = flask_app.test_client()
    workspace = client.get("/ui/clientes/CLI000001/workspace", headers={"HX-Request": "true"})
    decision_id = _decision_id(workspace.data)
    before = advisor_backend.customer_state("CLI000001")
    accepted = client.post(
        f"/ui/decisiones/{decision_id}/feedback",
        data={"resultado_final": "aceptada", "medio_probatorio": "registro_plataforma"},
        headers={"HX-Request": "true"},
    )
    assert accepted.status_code == 200
    assert advisor_backend.customer_state("CLI000001")["state_version"] == before["state_version"]
    activation_url = f"/ui/decisiones/{decision_id}/activacion"
    activated = client.post(
        activation_url, data={"evidence_reference": "ORDER-UI-001"},
        headers={"HX-Request": "true"},
    )
    assert activated.status_code == 200
    assert "Producto activado" in activated.text
    after = advisor_backend.customer_state("CLI000001")
    assert after["state_version"] == before["state_version"] + 1
    replay = client.post(
        activation_url, data={"evidence_reference": "ORDER-UI-001"},
        headers={"HX-Request": "true"},
    )
    assert replay.status_code == 200
    assert advisor_backend.customer_state("CLI000001")["state_version"] == after["state_version"]


@pytest.mark.parametrize("outcome,extra", [
    ("rechazada", {"motivo_rechazo": "precio", "rebate_usado": "true", "resultado_rebate": "rechazada"}),
    ("no_contactado", {}),
])
def test_rejection_no_contact_and_recalculation(flask_app, outcome, extra):
    client = flask_app.test_client()
    workspace = client.get("/ui/clientes/CLI000013/workspace", headers={"HX-Request": "true"})
    decision_id = _decision_id(workspace.data)
    data = {"resultado_final": outcome, "medio_probatorio": "registro_plataforma", **extra}
    saved = client.post(
        f"/ui/decisiones/{decision_id}/feedback", data=data, headers={"HX-Request": "true"},
    )
    assert saved.status_code == 200 and "Calcular una nueva recomendación" in saved.text
    recalculated = client.post(
        "/ui/clientes/CLI000013/recalcular", headers={"HX-Request": "true"},
    )
    assert recalculated.status_code == 200 and _decision_id(recalculated.data) != decision_id


def test_validation_conflict_csrf_and_autoescape(flask_app, advisor_backend):
    client = flask_app.test_client()
    workspace = client.get("/ui/clientes/CLI000002/workspace", headers={"HX-Request": "true"})
    decision_id = _decision_id(workspace.data)
    invalid = client.post(
        f"/ui/decisiones/{decision_id}/feedback",
        data={"resultado_final": "rechazada", "medio_probatorio": "chat_log"},
        headers={"HX-Request": "true"},
    )
    assert invalid.status_code == 422
    client.post(
        f"/ui/decisiones/{decision_id}/feedback",
        data={"resultado_final": "aceptada", "medio_probatorio": "chat_log"},
        headers={"HX-Request": "true"},
    )
    advisor_backend.engine.state_service.register_event(CustomerEventRequest(
        cliente_id="CLI000002", event_type="usage_updated", effective_at="2026-08-14T12:00:00Z",
        source="crm", idempotency_key="ui-stale-state", expected_state_version=0,
        changes={"consumo_datos_gb_prom": 10},
    ))
    conflict = client.post(
        f"/ui/decisiones/{decision_id}/activacion", data={"evidence_reference": "ORDER-STALE"},
        headers={"HX-Request": "true"},
    )
    assert conflict.status_code == 409 and "Conflicto de version" in conflict.text

    csrf_app = create_app({"TESTING": True, "SECRET_KEY": "test-csrf"}, advisor_backend)
    csrf_client = csrf_app.test_client()
    csrf_workspace = csrf_client.get("/ui/clientes/CLI000003/workspace", headers={"HX-Request": "true"})
    csrf_decision = _decision_id(csrf_workspace.data)
    rejected = csrf_client.post(
        f"/ui/decisiones/{csrf_decision}/contacto", headers={"HX-Request": "true"},
    )
    assert rejected.status_code == 400

    original = advisor_backend.workspace
    def malicious(cliente_id):
        context = original(cliente_id)
        context["result"]["sales_playbook"]["opening"] = "<script>alert(1)</script>"
        return context
    advisor_backend.workspace = malicious
    try:
        escaped = client.get("/ui/clientes/CLI000004/workspace", headers={"HX-Request": "true"})
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in escaped.text
        assert "<script>alert(1)</script>" not in escaped.text
    finally:
        advisor_backend.workspace = original


def test_hot_local_search_p95_is_under_one_second(advisor_backend):
    advisor_backend.workspace("CLI000005")
    samples = []
    for cliente_id in ("CLI000005", "CLI000006", "CLI000007", "CLI000008", "CLI000009"):
        started = time.perf_counter()
        advisor_backend.workspace(cliente_id)
        samples.append(time.perf_counter() - started)
    samples.sort()
    assert max(samples) < 1.0


def test_visible_personalized_metrics_vary_between_clients(advisor_backend):
    rows = advisor_backend.engine.rank_many([
        "CLI000001", "CLI000002", "CLI000003", "CLI000004", "CLI000005",
        "CLI000006", "CLI000007", "CLI000008", "CLI000009", "CLI000010",
    ])
    assert rows["score"].round(2).nunique() > 1
    assert rows["p_aceptacion"].round(2).nunique() > 1


def test_advisor_command_smoke(monkeypatch, flask_app):
    from nbo.advisor_app import cli
    served = {}
    monkeypatch.setattr(cli, "create_app", lambda: flask_app)
    monkeypatch.setattr(cli, "serve", lambda app, **kwargs: served.update(kwargs))
    monkeypatch.setattr(sys, "argv", ["nbo-advisor", "--no-browser", "--port", "5051"])
    cli.main()
    assert served == {"host": "127.0.0.1", "port": 5051, "threads": 4}
