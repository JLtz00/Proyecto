from __future__ import annotations

import atexit
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from .advisor_local import LocalAdvisorApi
from .advisor_ui import AdvisorApiError
from .engine import NBOEngine
from .features import mt_stage
from .jury import load_mvp_evidence


MAIN_CUSTOMER_ID = "CLI000001"


class JuryFlowError(AdvisorApiError):
    """Una accion de la demostracion se intento fuera de su secuencia."""

    def __init__(self, message: str):
        super().__init__(message, 409)


class JurySession:
    """Sesion unica y reiniciable para una presentacion local."""

    PHASES = ("ready", "started", "accepted", "activated", "rejected", "recalculated")

    def __init__(
        self,
        backend_factory: Callable[[Path], LocalAdvisorApi] | None = None,
        temp_dir: str | Path | None = None,
    ) -> None:
        self._backend_factory = backend_factory or (
            lambda path: LocalAdvisorApi(NBOEngine(persist=True, database_path=path))
        )
        self._temp_dir = Path(temp_dir) if temp_dir else None
        self._lock = threading.RLock()
        self.backend: LocalAdvisorApi
        self.database_path: Path
        self.phase = "ready"
        self.journey: dict[str, Any] = {}
        self._profiles: list[dict[str, Any]] = []
        self._evidence: dict[str, Any] = {}
        self._economics: dict[str, Any] = {}
        self.reset()
        atexit.register(self.cleanup)

    def _temporary_database(self) -> Path:
        directory = str(self._temp_dir) if self._temp_dir else None
        descriptor, raw_path = tempfile.mkstemp(prefix="nbo-jury-", suffix=".sqlite3", dir=directory)
        os.close(descriptor)
        path = Path(raw_path).resolve()
        path.unlink()
        return path

    @staticmethod
    def _remove_database(path: Path | None) -> None:
        if path is None or not path.name.startswith("nbo-jury-"):
            return
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass

    def cleanup(self) -> None:
        with self._lock:
            self._remove_database(getattr(self, "database_path", None))

    def _select_profiles(self) -> list[dict[str, Any]]:
        wanted = (
            ("Ruta hacia MT", {"falta_internet_hogar", "falta_movil_postpago"}),
            ("Elegible para MT", {"elegible_mt"}),
            ("Ya posee MT", {"ya_es_mt"}),
        )
        frame = self.backend.engine.customer_index
        rows: list[dict[str, Any]] = []
        used: set[str] = set()
        for label, stages in wanted:
            customer_id = next(
                (
                    str(customer_id)
                    for customer_id, customer in frame.iterrows()
                    if str(customer_id) not in used and mt_stage(customer) in stages
                ),
                None,
            )
            if customer_id is None:
                continue
            used.add(customer_id)
            workspace = self.backend.workspace(customer_id)
            result = workspace["result"]
            rows.append({
                "label": label,
                "cliente_id": customer_id,
                "stage": result["cliente"]["etapa_mt"],
                "offer": result["recommendation"],
                "active_offer_ids": workspace["state"]["active_offer_ids"],
                "duplicate_mt_acquisition": bool(
                    result["cliente"]["es_movistar_total"]
                    and result["recommendation"]["es_mt"]
                ),
            })
        return rows

    def reset(self) -> dict[str, Any]:
        with self._lock:
            old_path = getattr(self, "database_path", None)
            new_path = self._temporary_database()
            try:
                backend = self._backend_factory(new_path)
            except Exception:
                self._remove_database(new_path)
                raise
            self.backend = backend
            self.database_path = new_path
            self.phase = "ready"
            self.journey = {}
            self._profiles = self._select_profiles()
            self._evidence = load_mvp_evidence(self.backend.engine)
            self._economics = self.backend.economics(MAIN_CUSTOMER_ID, {})
            self._remove_database(old_path)
            return self.context("Demostracion reiniciada en una base temporal nueva.")

    def _require(self, expected: str) -> None:
        if self.phase != expected:
            raise JuryFlowError(
                f"Paso fuera de orden: la accion requiere '{expected}' y la demostracion esta en '{self.phase}'."
            )

    def start(self) -> dict[str, Any]:
        with self._lock:
            self._require("ready")
            workspace = self.backend.workspace(MAIN_CUSTOMER_ID)
            self.journey = {
                "initial": workspace,
                "current": workspace,
                "initial_active_offers": list(workspace["state"]["active_offer_ids"]),
                "initial_state_version": int(workspace["state"]["state_version"]),
            }
            self.phase = "started"
            return self.context("Caso iniciado: la recomendacion fue calculada por el motor activo.")

    def accept(self) -> dict[str, Any]:
        with self._lock:
            self._require("started")
            decision_id = self.journey["current"]["result"]["decision_id"]
            self.backend.record_contact(decision_id)
            workspace = self.backend.record_feedback(decision_id, {
                "resultado_final": "aceptada",
                "medio_probatorio": "registro_plataforma",
                "rebate_usado": False,
            })
            self.journey["accepted"] = workspace
            self.journey["current"] = workspace
            self.phase = "accepted"
            return self.context("Aceptacion registrada: la cartera de productos aun no cambio.")

    def activate(self) -> dict[str, Any]:
        with self._lock:
            self._require("accepted")
            decision_id = self.journey["current"]["result"]["decision_id"]
            workspace = self.backend.activate_decision(
                decision_id, f"JURY-ORDER-{decision_id[:8].upper()}"
            )
            self.journey["activated"] = workspace
            self.journey["current"] = workspace
            self.phase = "activated"
            return self.context("Activacion confirmada con evidencia: estado y NBO fueron recalculados.")

    def reject(self) -> dict[str, Any]:
        with self._lock:
            self._require("activated")
            decision_id = self.journey["current"]["result"]["decision_id"]
            self.backend.record_contact(decision_id)
            workspace = self.backend.record_feedback(decision_id, {
                "resultado_final": "rechazada",
                "motivo_rechazo": "precio",
                "medio_probatorio": "registro_plataforma",
                "rebate_usado": False,
            })
            self.journey["rejected"] = workspace
            self.journey["current"] = workspace
            self.phase = "rejected"
            return self.context("Rechazo por precio registrado: se aplico cooldown y fecha de recontacto.")

    def recalculate(self) -> dict[str, Any]:
        with self._lock:
            self._require("rejected")
            workspace = self.backend.workspace(MAIN_CUSTOMER_ID)
            self.journey["recalculated"] = workspace
            self.journey["current"] = workspace
            self.phase = "recalculated"
            return self.context("Nueva NBO calculada con la activacion y el rechazo ya incorporados.")

    def context(self, toast: str | None = None) -> dict[str, Any]:
        with self._lock:
            return {
                "phase": self.phase,
                "phase_index": self.PHASES.index(self.phase),
                "phases": self.PHASES,
                "journey": self.journey,
                "profiles": self._profiles,
                "evidence": self._evidence,
                "economics": self._economics,
                "health": self.backend.health(),
                "toast": toast,
            }
