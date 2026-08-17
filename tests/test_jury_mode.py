from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from nbo.advisor_app import create_app
from nbo.jury import load_mvp_evidence
from nbo.jury_session import JurySession


@pytest.fixture(scope="module")
def jury_session(tmp_path_factory):
    session = JurySession(temp_dir=tmp_path_factory.mktemp("jury-databases"))
    yield session
    session.cleanup()


@pytest.fixture
def jury_app(jury_session):
    return create_app(
        {
            "TESTING": True, "JURY_MODE": True, "SECRET_KEY": "jury-test",
            "WTF_CSRF_ENABLED": False,
        },
        jury_session=jury_session,
    )


def test_normal_mode_does_not_expose_jury_routes():
    app = create_app({"TESTING": True}, backend=object())
    response = app.test_client().get("/jury")
    assert response.status_code == 404


def test_jury_page_is_local_accessible_and_sends_no_business_ids(jury_app, jury_session):
    jury_session.reset()
    response = jury_app.test_client().get("/jury")
    assert response.status_code == 200
    assert "Modo Jurado" in response.text
    assert "Evidencia del MVP" in response.text
    assert "Simulación · no ventas reales" in response.text
    assert "Arquitectura futura" in response.text
    assert "https://" not in response.text and "http://" not in response.text
    for field in ("cliente_id", "oferta_id", "decision_id", "model_version", "state_version"):
        assert f'name="{field}"' not in response.text
    assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert "Saltar al contenido" in response.text


def test_closed_loop_transitions_and_out_of_order_conflict(jury_app, jury_session):
    jury_session.reset()
    client = jury_app.test_client()
    headers = {"HX-Request": "true"}

    conflict = client.post("/jury/scenario/accept", headers=headers)
    assert conflict.status_code == 409
    assert "Paso fuera de orden" in conflict.text

    assert client.post("/jury/scenario/start", headers=headers).status_code == 200
    initial = jury_session.journey["initial"]
    initial_offers = initial["state"]["active_offer_ids"]
    initial_version = initial["state"]["state_version"]

    accepted = client.post("/jury/scenario/accept", headers=headers)
    assert accepted.status_code == 200
    assert jury_session.journey["accepted"]["state"]["active_offer_ids"] == initial_offers
    assert jury_session.journey["accepted"]["state"]["state_version"] == initial_version

    activated = client.post("/jury/scenario/activate", headers=headers)
    assert activated.status_code == 200
    activated_workspace = jury_session.journey["activated"]
    assert activated_workspace["state"]["state_version"] == initial_version + 1
    assert activated_workspace["result"]["decision_id"] != initial["result"]["decision_id"]

    rejected = client.post("/jury/scenario/reject", headers=headers)
    assert rejected.status_code == 200
    action = jury_session.journey["rejected"]["interaction"]["feedback"]["post_rejection_action"]
    assert action["trigger_reason"] == "precio"
    assert action["wait_days"] > 0

    recalculated = client.post("/jury/scenario/recalculate", headers=headers)
    assert recalculated.status_code == 200
    assert jury_session.phase == "recalculated"
    assert jury_session.journey["recalculated"]["result"]["decision_id"] != activated_workspace["result"]["decision_id"]


def test_reset_is_repeatable_and_never_uses_operational_sqlite(jury_app, jury_session):
    operational = Path("artifacts/nbo.sqlite3").resolve()
    before = (operational.stat().st_size, operational.stat().st_mtime_ns) if operational.exists() else None
    first = jury_session.database_path
    response = jury_app.test_client().post(
        "/jury/scenario/reset", headers={"HX-Request": "true"},
    )
    second = jury_session.database_path
    assert response.status_code == 200
    assert first != second
    assert not first.exists()
    assert second.exists()
    assert second != operational
    assert jury_session.phase == "ready"
    after = (operational.stat().st_size, operational.stat().st_mtime_ns) if operational.exists() else None
    assert after == before


def test_jury_csrf_and_autoescape(jury_session):
    app = create_app({
        "TESTING": True,
        "JURY_MODE": True,
        "SECRET_KEY": "csrf-test",
        "WTF_CSRF_ENABLED": True,
    }, jury_session=jury_session)
    client = app.test_client()
    client.get("/jury")
    rejected = client.post("/jury/scenario/start", headers={"HX-Request": "true"})
    assert rejected.status_code == 400

    jury_session._profiles[0]["label"] = "<script>alert(1)</script>"
    try:
        escaped = app.test_client().get("/jury")
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in escaped.text
        assert "<script>alert(1)</script>" not in escaped.text
    finally:
        jury_session._profiles[0]["label"] = "Ruta hacia MT"


def test_stale_evidence_is_blocked(tmp_path, monkeypatch):
    artifact = tmp_path / "artifacts" / "active"
    reports = tmp_path / "reports"
    artifact.mkdir(parents=True)
    reports.mkdir()
    (artifact / "metadata.json").write_text(json.dumps({
        "versions": {"model_version": "active_v1"}, "metrics": {"group_split": {}},
    }), encoding="utf-8")
    (reports / "evaluation_v3.json").write_text(
        json.dumps({"model_version": "old_v0"}), encoding="utf-8",
    )
    monkeypatch.setattr("nbo.jury.ROOT", tmp_path)

    class Engine:
        versions = {"model_version": "active_v1"}
        artifact_dir = artifact
        config = {"project": {"artifact_dir": str(tmp_path / "artifacts")}}

    evidence = load_mvp_evidence(Engine())
    assert evidence["ranking"]["v3"] is None
    assert any(item["report"] == "evaluation_v3.json" for item in evidence["blocked_reports"])


def test_jury_cli_uses_same_local_server(monkeypatch):
    from nbo.advisor_app import cli

    marker = object()
    served = {}
    monkeypatch.setattr(cli, "create_app", lambda config: marker)
    monkeypatch.setattr(cli, "serve", lambda app, **kwargs: served.update({"app": app, **kwargs}))
    monkeypatch.setattr(sys, "argv", ["nbo-advisor", "--jury", "--no-browser", "--port", "5052"])
    cli.main()
    assert served == {"app": marker, "host": "127.0.0.1", "port": 5052, "threads": 4}


def test_hot_jury_steps_stay_under_one_second(jury_app, jury_session):
    jury_session.reset()
    client = jury_app.test_client()
    durations = []
    for action in ("start", "accept", "activate", "reject", "recalculate"):
        started = time.perf_counter()
        response = client.post(f"/jury/scenario/{action}", headers={"HX-Request": "true"})
        durations.append(time.perf_counter() - started)
        assert response.status_code == 200
    assert max(durations) < 1.0
