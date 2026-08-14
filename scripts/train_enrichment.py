"""Entrenador oficial de modelos de enriquecimiento (churn + personas).

Se ejecuta como script (`python scripts/train_enrichment.py`) para que joblib
pickle referencie las clases desde `nbo.enrichment` y no desde `__main__`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nbo.enrichment import train_all_enrichment


def _resolve_artifact_dir(explicit: str | None) -> str:
    if explicit:
        return explicit
    manifest_path = Path("artifacts/current.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        path = Path(manifest["path"])
        return str(path if path.is_absolute() else Path("artifacts") / path)
    return "artifacts/nbo_v2"


def main() -> None:
    parser = argparse.ArgumentParser(description="Entrena modelos de enriquecimiento (churn, personas).")
    parser.add_argument("--dataset", default="dataset/dataset_clientes.csv")
    parser.add_argument("--artifact-dir", default=None)
    parser.add_argument("--k-personas", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    artifact_dir = _resolve_artifact_dir(args.artifact_dir)
    summary = train_all_enrichment(
        args.dataset, artifact_dir, seed=args.seed, k_personas=args.k_personas
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
