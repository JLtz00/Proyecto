from __future__ import annotations

import json
from pathlib import Path

import yaml

from nbo.bootstrap import check_environment
from nbo.engine import NBOEngine


def test_pretrained_manifest_is_portable_and_reference_cases_work():
    manifest = json.loads(Path("artifacts/current.json").read_text(encoding="utf-8"))
    assert not Path(manifest["path"]).is_absolute()
    report = check_environment()
    assert report["ready"] is True
    assert report["manifest_portable"] is True
    assert [item["cliente_id"] for item in report["reference_cases"]] == [
        "CLI000001", "CLI000013", "CLI000018",
    ]


def test_engine_resolves_relative_manifest_from_custom_artifact_root(tmp_path):
    source = Path("artifacts/nbo_v2").resolve()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    (artifact_root / "current.json").write_text(
        json.dumps({"version": "nbo_v2", "path": str(source)}), encoding="utf-8",
    )
    config = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    config["project"]["data_dir"] = str(Path("dataset").resolve())
    config["project"]["artifact_dir"] = str(artifact_root)
    config["project"]["database_path"] = str(tmp_path / "nbo.sqlite3")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    engine = NBOEngine(str(config_path), persist=False)
    assert engine.versions["model_version"] == "nbo_v2"
