from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .config import load_config
from .config import ROOT
from .data import CATALOG_FILE, CUSTOMER_FILE, HISTORY_FILE
from .engine import ArtifactUnavailable, NBOEngine


REFERENCE_CLIENTS = ("CLI000001", "CLI000013", "CLI000018")
REQUIRED_ARTIFACTS = (
    "contact.joblib", "acceptance.joblib", "rejection.joblib", "metadata.json",
    "feature_schema.json",
)


def _json_version(path: Path, *, nested: bool = False) -> str | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if nested:
        return payload.get("versions", {}).get("model_version")
    return payload.get("model_version") or payload.get("version")


def canonical_text_sha256(path: Path) -> str:
    """Hash textual estable entre checkouts CRLF (Windows) y LF (Linux)."""
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def check_environment(config_path: str | None = None) -> dict:
    config = load_config(config_path)
    data_dir = Path(config["project"]["data_dir"])
    artifact_root = Path(config["project"]["artifact_dir"])
    manifest_path = artifact_root / "current.json"
    data_files = {
        name: (data_dir / name).exists()
        for name in (CUSTOMER_FILE, CATALOG_FILE, HISTORY_FILE)
    }
    expected_hashes: dict[str, str] = {}
    checksum_path = data_dir / "SHA256SUMS"
    if checksum_path.exists():
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            digest, filename = line.split(maxsplit=1)
            expected_hashes[filename.strip()] = digest.lower()
    data_hashes = {}
    for name in (CUSTOMER_FILE, CATALOG_FILE, HISTORY_FILE):
        path = data_dir / name
        actual = canonical_text_sha256(path) if path.exists() else None
        data_hashes[name] = {
            "expected": expected_hashes.get(name), "actual": actual,
            "matches": bool(actual and expected_hashes.get(name) == actual),
            "mode": "text_lf_v1",
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

    configured_version = str(config["project"].get("model_version", ""))
    evidence_paths = {
        "manifest": manifest_path,
        "metadata": artifact_dir / "metadata.json" if artifact_dir else artifact_root / "missing-metadata.json",
        "audit": artifact_dir / "audit.json" if artifact_dir else artifact_root / "missing-audit.json",
        "evaluation_v2": artifact_root / "evaluation_v2.json",
        "evaluation_v3": ROOT / "reports" / "evaluation_v3.json",
        "batch_100k": artifact_root / "recomendaciones.report.json",
        "numeric_documentation": ROOT / "docs" / "evidence_manifest.json",
    }
    nested_versions = {"metadata"}
    evidence_versions = {
        name: _json_version(path, nested=name in nested_versions)
        for name, path in evidence_paths.items()
    }
    evidence_consistent = bool(configured_version) and all(
        version == configured_version for version in evidence_versions.values()
    )

    report = {
        "python": sys.version.split()[0],
        "data": data_files,
        "data_hashes": data_hashes,
        "manifest": str(manifest_path),
        "manifest_portable": bool(manifest and not Path(manifest["path"]).is_absolute()),
        "artifact_dir": str(artifact_dir) if artifact_dir else None,
        "artifacts": artifact_files,
        "configured_model_version": configured_version,
        "evidence_versions": evidence_versions,
        "evidence_consistent": evidence_consistent,
        "ready": all(data_files.values()) and all(item["matches"] for item in data_hashes.values())
        and bool(artifact_files) and all(artifact_files.values()) and evidence_consistent,
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
