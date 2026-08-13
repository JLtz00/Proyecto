from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .data import CATALOG_FILE, CUSTOMER_FILE, HISTORY_FILE
from .engine import ArtifactUnavailable, NBOEngine


REFERENCE_CLIENTS = ("CLI000001", "CLI000013", "CLI000018")
REQUIRED_ARTIFACTS = (
    "contact.joblib", "acceptance.joblib", "rejection.joblib", "metadata.json",
    "feature_schema.json",
)


def check_environment(config_path: str | None = None) -> dict:
    config = load_config(config_path)
    data_dir = Path(config["project"]["data_dir"])
    artifact_root = Path(config["project"]["artifact_dir"])
    manifest_path = artifact_root / "current.json"
    data_files = {
        name: (data_dir / name).exists()
        for name in (CUSTOMER_FILE, CATALOG_FILE, HISTORY_FILE)
    }
    manifest = None
    artifact_dir = None
    artifact_files: dict[str, bool] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact_dir = Path(manifest["path"])
        if not artifact_dir.is_absolute():
            artifact_dir = (artifact_root / artifact_dir).resolve()
        artifact_files = {
            name: (artifact_dir / name).exists() for name in REQUIRED_ARTIFACTS
        }

    report = {
        "python": sys.version.split()[0],
        "data": data_files,
        "manifest": str(manifest_path),
        "manifest_portable": bool(manifest and not Path(manifest["path"]).is_absolute()),
        "artifact_dir": str(artifact_dir) if artifact_dir else None,
        "artifacts": artifact_files,
        "ready": all(data_files.values()) and bool(artifact_files) and all(artifact_files.values()),
        "reference_cases": [],
    }
    if report["ready"]:
        engine = NBOEngine(config_path, persist=False)
        report["versions"] = engine.versions
        for cliente_id in REFERENCE_CLIENTS:
            result = engine.recommend_override(engine.customer_index.loc[cliente_id])
            report["reference_cases"].append({
                "cliente_id": cliente_id,
                "stage": result.cliente.etapa_mt,
                "offer_id": result.recommendation.oferta_id,
                "channel": result.recommendation.canal,
            })
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verifica datos, artefactos y casos de referencia del proyecto NBO.",
    )
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        report = check_environment(args.config)
    except (ArtifactUnavailable, FileNotFoundError, ValueError) as exc:
        print(json.dumps({"ready": False, "error": str(exc)}, indent=2, ensure_ascii=False))
        raise SystemExit(1) from exc
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
