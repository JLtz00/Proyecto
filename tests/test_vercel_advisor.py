from __future__ import annotations

import json
from pathlib import Path

from nbo.advisor_app import create_app
from nbo.advisor_app import vercel
from nbo.models import load_artifact


class StubBackend:
    def health(self):
        return {"status": "ok", "model_version": "nbo_v2_1"}


def test_read_only_advisor_does_not_register_jury_routes():
    app = create_app(
        {
            "TESTING": True,
            "ADVISOR_READ_ONLY": True,
            "JURY_MODE": False,
            "WTF_CSRF_ENABLED": False,
        },
        backend=StubBackend(),
    )
    client = app.test_client()

    assert client.get("/").status_code == 200
    assert client.get("/jury").status_code == 404
    assert client.post("/ui/decisiones/decision-1/contacto").status_code == 405


def test_vercel_factory_uses_temporary_database_and_read_only_mode(monkeypatch, tmp_path):
    database_path = tmp_path / "vercel.sqlite3"
    captured: dict[str, object] = {}

    class FakeEngine:
        def __init__(self, *, persist, database_path):
            captured.update(persist=persist, database_path=database_path)
            self.store = object()
            self.state_service = object()

    class FakeBackend:
        def __init__(self, engine):
            captured["engine"] = engine

    monkeypatch.setenv("NBO_VERCEL_DATABASE_PATH", str(database_path))
    monkeypatch.setattr(vercel, "NBOEngine", FakeEngine)
    monkeypatch.setattr(vercel, "LocalAdvisorApi", FakeBackend)

    app = vercel.create_vercel_app()

    assert app.config["ADVISOR_READ_ONLY"] is True
    assert app.config["JURY_MODE"] is False
    assert captured["persist"] is True
    assert captured["database_path"] == database_path.resolve()
    assert Path(captured["database_path"]) != Path("artifacts/nbo.sqlite3").resolve()


def test_vercel_runtime_dependencies_match_selected_inference_artifacts():
    artifact_root = Path("artifacts/nbo_v2_1")
    kinds = {
        load_artifact(artifact_root / name).model_kind
        for name in ("contact.joblib", "acceptance.joblib", "rejection.joblib")
    }

    assert "catboost" not in kinds


def test_public_assets_are_exact_copies_of_advisor_assets():
    source = Path("src/nbo/advisor_app/static")
    public = Path("public/static")
    relative_paths = (
        "icons.svg",
        "css/advisor.css",
        "js/advisor.js",
        "js/theme-init.js",
        "vendor/HTMX-LICENSE.txt",
        "vendor/htmx.min.js",
        "img/icon_nbo.ico",
        "img/icon_nbo_ui.ico",
        "img/Logo_nbo.png",
        "img/Logo_nbo_ui.png",
    )

    for relative_path in relative_paths:
        assert (public / relative_path).read_bytes() == (source / relative_path).read_bytes()


def test_vercel_uses_automatic_install_and_minimal_requirements():
    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    ignored = Path(".vercelignore").read_text(encoding="utf-8").splitlines()

    assert "installCommand" not in config
    assert "catboost" not in requirements.lower()
    assert "requirements.lock" not in requirements
    assert "pyproject.toml" in ignored and "requirements.lock" in ignored
