from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def make_group_assignments(client_ids: pd.Series, seed: int = 42) -> dict[str, str]:
    unique = client_ids.drop_duplicates().astype(str).to_numpy().copy()
    np.random.default_rng(seed).shuffle(unique)
    n = len(unique)
    train_end, validation_end = int(n * 0.70), int(n * 0.85)
    return {
        **{value: "train" for value in unique[:train_end]},
        **{value: "validation" for value in unique[train_end:validation_end]},
        **{value: "test" for value in unique[validation_end:]},
    }


def apply_group_assignments(client_ids: pd.Series, assignments: dict[str, str]) -> np.ndarray:
    split = client_ids.astype(str).map(assignments)
    if split.isna().any():
        missing = client_ids.loc[split.isna()].astype(str).drop_duplicates().head(10).tolist()
        raise ValueError(f"Clientes sin split: {missing}")
    return split.to_numpy(dtype=str)


def save_split_manifest(assignments: dict[str, str], path: str | Path, seed: int) -> None:
    counts = pd.Series(assignments).value_counts().to_dict()
    payload = {"seed": seed, "counts": counts, "assignments": assignments}
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_split_manifest(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def temporal_split(dates: pd.Series) -> np.ndarray:
    month = pd.to_datetime(dates).dt.month
    return np.where(month <= 4, "train", np.where(month == 5, "validation", "test"))
