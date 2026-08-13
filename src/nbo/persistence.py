from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS model_versions (
    model_version TEXT PRIMARY KEY,
    feature_version TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    catalog_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nbo_decisions (
    decision_id TEXT PRIMARY KEY,
    cliente_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    catalog_version TEXT NOT NULL,
    top_offer_id TEXT NOT NULL,
    top_channel TEXT NOT NULL,
    p_contact REAL NOT NULL,
    p_acceptance REAL NOT NULL,
    p_sale REAL NOT NULL,
    score REAL NOT NULL,
    predicted_rejection TEXT,
    rebate_strategy TEXT,
    response_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nbo_candidates (
    decision_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    offer_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    p_contact REAL NOT NULL,
    p_acceptance REAL NOT NULL,
    p_sale REAL NOT NULL,
    score REAL NOT NULL,
    reason_codes TEXT NOT NULL,
    displayed INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (decision_id, rank),
    FOREIGN KEY (decision_id) REFERENCES nbo_decisions(decision_id)
);
CREATE TABLE IF NOT EXISTS feedback_events (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    final_result TEXT NOT NULL,
    rejection_reason TEXT,
    proof_type TEXT NOT NULL,
    rebate_used INTEGER NOT NULL,
    rebate_result TEXT,
    post_rejection_action_json TEXT,
    FOREIGN KEY (decision_id) REFERENCES nbo_decisions(decision_id)
);
CREATE TABLE IF NOT EXISTS funnel_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    channel TEXT,
    offer_id TEXT,
    proof_type TEXT,
    evidence_reference TEXT,
    rejection_reason TEXT,
    UNIQUE (decision_id, event_type),
    FOREIGN KEY (decision_id) REFERENCES nbo_decisions(decision_id)
);
CREATE TABLE IF NOT EXISTS playbook_exposures (
    exposure_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    experiment_version TEXT NOT NULL,
    variant TEXT NOT NULL,
    channel TEXT NOT NULL,
    mt_stage TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (decision_id) REFERENCES nbo_decisions(decision_id)
);
CREATE TABLE IF NOT EXISTS llm_render_events (
    render_id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT NOT NULL,
    render_status TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    fallback_reason TEXT,
    FOREIGN KEY (decision_id) REFERENCES nbo_decisions(decision_id)
);
CREATE TABLE IF NOT EXISTS customer_state_events (
    event_id TEXT PRIMARY KEY,
    cliente_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    source TEXT NOT NULL,
    decision_id TEXT,
    oferta_id TEXT,
    changes_before_json TEXT NOT NULL,
    changes_after_json TEXT NOT NULL,
    evidence_type TEXT,
    evidence_reference TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    correction_of_event_id TEXT,
    state_version_before INTEGER NOT NULL,
    state_version_after INTEGER NOT NULL,
    FOREIGN KEY (decision_id) REFERENCES nbo_decisions(decision_id),
    FOREIGN KEY (correction_of_event_id) REFERENCES customer_state_events(event_id)
);
CREATE TABLE IF NOT EXISTS customer_event_rejections (
    rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    cliente_id TEXT,
    idempotency_key TEXT,
    reason TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_customer ON nbo_decisions(cliente_id);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON nbo_decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_funnel_decision ON funnel_events(decision_id);
CREATE INDEX IF NOT EXISTS idx_playbook_variant ON playbook_exposures(experiment_version, variant);
CREATE INDEX IF NOT EXISTS idx_state_events_customer_effective
ON customer_state_events(cliente_id, effective_at, recorded_at, event_id);
CREATE TRIGGER IF NOT EXISTS prevent_customer_state_event_update
BEFORE UPDATE ON customer_state_events
BEGIN SELECT RAISE(ABORT, 'customer_state_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS prevent_customer_state_event_delete
BEFORE DELETE ON customer_state_events
BEGIN SELECT RAISE(ABORT, 'customer_state_events is append-only'); END;
"""


class StateVersionConflict(ValueError):
    pass


class DecisionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            feedback_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(feedback_events)")
            }
            if "post_rejection_action_json" not in feedback_columns:
                connection.execute("ALTER TABLE feedback_events ADD COLUMN post_rejection_action_json TEXT")
            decision_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(nbo_decisions)")
            }
            additions = {
                "state_version": "INTEGER NOT NULL DEFAULT 0",
                "state_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
                "applied_event_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "playbook_version": "TEXT",
                "decision_schema_version": "TEXT",
            }
            for name, definition in additions.items():
                if name not in decision_columns:
                    connection.execute(f"ALTER TABLE nbo_decisions ADD COLUMN {name} {definition}")

    def register_version(self, versions: dict[str, str], metadata: dict) -> None:
        registered_metadata = {**metadata, "runtime_versions": versions}
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO model_versions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    versions["model_version"], versions["feature_version"], versions["rules_version"],
                    versions["catalog_version"], datetime.now(timezone.utc).isoformat(),
                    json.dumps(registered_metadata, ensure_ascii=False),
                ),
            )

    def save_decision(self, payload: dict[str, Any]) -> None:
        top = payload["recommendation"]
        versions = payload["versions"]
        objections = payload["rejection_prediction"]
        candidates = [top] + payload["alternatives"]
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO nbo_decisions
                (decision_id, cliente_id, created_at, model_version, feature_version, rules_version,
                 catalog_version, top_offer_id, top_channel, p_contact, p_acceptance, p_sale, score,
                 predicted_rejection, rebate_strategy, response_json, state_version, state_snapshot_json,
                 applied_event_ids_json, playbook_version, decision_schema_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload["decision_id"], payload["cliente"]["cliente_id"], datetime.now(timezone.utc).isoformat(),
                    versions["model_version"], versions["feature_version"], versions["rules_version"], versions["catalog_version"],
                    top["oferta_id"], top["canal"], top["probabilidad_contacto"], top["probabilidad_aceptacion"],
                    top["probabilidad_venta"], top["score"], objections[0]["motivo"] if objections else None,
                    payload["rebate"]["strategy"], json.dumps(payload, ensure_ascii=False, default=str),
                    int(payload.get("state_version", 0)),
                    json.dumps(payload.get("state_snapshot", payload.get("cliente", {})), ensure_ascii=False),
                    json.dumps(payload.get("applied_state_event_ids", []), ensure_ascii=False),
                    versions.get("playbook_version"), payload.get("decision_schema_version"),
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO funnel_events
                (decision_id, created_at, event_type, channel, offer_id)
                VALUES (?, ?, 'classified', ?, ?)""",
                (payload["decision_id"], datetime.now(timezone.utc).isoformat(), top["canal"], top["oferta_id"]),
            )
            for rank, item in enumerate(candidates, 1):
                reasons = item.get("reason_codes", [])
                connection.execute(
                    "INSERT INTO nbo_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (
                        payload["decision_id"], rank, item["oferta_id"], item["canal"],
                        item["probabilidad_contacto"], item["probabilidad_aceptacion"], item["probabilidad_venta"],
                        item["score"], json.dumps(reasons, ensure_ascii=False),
                    ),
                )
            experiment = payload.get("playbook_experiment")
            if experiment:
                connection.execute(
                    """INSERT INTO playbook_exposures
                    (exposure_id, decision_id, experiment_version, variant, channel, mt_stage, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        experiment["exposure_id"], payload["decision_id"], experiment["experiment_version"],
                        experiment["variant"], top["canal"], payload["cliente"]["etapa_mt"],
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    def save_ranked_batch(self, records: list[dict[str, Any]], versions: dict[str, str]) -> None:
        """Persiste Top 1 de un chunk en una sola transacción."""
        if not records:
            return
        with self.connect() as connection:
            decision_rows = []
            funnel_rows = []
            candidate_rows = []
            for item in records:
                decision_rows.append((
                    item["decision_id"], item["cliente_id"], item["created_at"], versions["model_version"],
                    versions["feature_version"], versions["rules_version"], versions["catalog_version"],
                    item["oferta_id"], item["canal"], item["p_contacto"], item["p_aceptacion"],
                    item["p_venta"], item["score"], None, "batch_pending_detail", "{}",
                ))
                funnel_rows.append((item["decision_id"], item["created_at"], item["canal"], item["oferta_id"]))
                candidate_rows.append((
                    item["decision_id"], 1, item["oferta_id"], item["canal"], item["p_contacto"],
                    item["p_aceptacion"], item["p_venta"], item["score"],
                    json.dumps(["BATCH_TOP1"], ensure_ascii=False), 1,
                ))
            connection.executemany(
                """INSERT INTO nbo_decisions
                (decision_id, cliente_id, created_at, model_version, feature_version, rules_version,
                 catalog_version, top_offer_id, top_channel, p_contact, p_acceptance, p_sale, score,
                 predicted_rejection, rebate_strategy, response_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", decision_rows,
            )
            connection.executemany(
                "INSERT OR IGNORE INTO funnel_events (decision_id, created_at, event_type, channel, offer_id) VALUES (?, ?, 'classified', ?, ?)",
                funnel_rows,
            )
            connection.executemany(
                "INSERT INTO nbo_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", candidate_rows
            )

    def decision_exists(self, decision_id: str) -> bool:
        with self.connect() as connection:
            return connection.execute("SELECT 1 FROM nbo_decisions WHERE decision_id = ?", (decision_id,)).fetchone() is not None

    def get_decision(self, decision_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM nbo_decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
        if row is None:
            raise KeyError(decision_id)
        return dict(row)

    def get_decision_payload(self, decision_id: str) -> dict[str, Any]:
        row = self.get_decision(decision_id)
        if row["response_json"] in {None, "{}"}:
            raise ValueError("trace_unavailable_for_legacy_decision")
        return json.loads(row["response_json"])

    def save_llm_render_event(self, payload: dict[str, Any]) -> int:
        if not self.decision_exists(payload["decision_id"]):
            raise KeyError(payload["decision_id"])
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO llm_render_events
                (decision_id, created_at, provider, model, prompt_version, render_status,
                 validation_status, latency_ms, fallback_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload["decision_id"], datetime.now(timezone.utc).isoformat(), payload["provider"],
                    payload.get("model"), payload["prompt_version"], payload["render_status"],
                    payload["validation_status"], payload["latency_ms"], payload.get("fallback_reason"),
                ),
            )
            return int(cursor.lastrowid)

    def operational_rejections(self, cliente_ids: list[str]) -> list[dict[str, Any]]:
        """Rechazos observados por la operación para aplicar cooldown en decisiones futuras."""
        if not cliente_ids:
            return []
        placeholders = ",".join("?" for _ in cliente_ids)
        query = f"""
            SELECT d.cliente_id, d.top_offer_id AS oferta_id, f.created_at, d.decision_id
            FROM feedback_events f
            JOIN nbo_decisions d ON d.decision_id = f.decision_id
            WHERE f.final_result = 'rechazada' AND d.cliente_id IN ({placeholders})
            UNION ALL
            SELECT d.cliente_id, e.offer_id AS oferta_id, e.created_at, d.decision_id
            FROM funnel_events e
            JOIN nbo_decisions d ON d.decision_id = e.decision_id
            WHERE e.event_type = 'rejected' AND d.cliente_id IN ({placeholders})
        """
        with self.connect() as connection:
            rows = connection.execute(query, [*cliente_ids, *cliente_ids]).fetchall()
        return [dict(row) for row in rows]

    def save_feedback(self, payload: dict[str, Any]) -> int:
        if not self.decision_exists(payload["decision_id"]):
            raise KeyError(payload["decision_id"])
        try:
            with self.connect() as connection:
                cursor = connection.execute(
                    """INSERT INTO feedback_events
                    (decision_id, created_at, final_result, rejection_reason, proof_type, rebate_used, rebate_result,
                     post_rejection_action_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        payload["decision_id"], datetime.now(timezone.utc).isoformat(), payload["resultado_final"],
                        payload.get("motivo_rechazo"), payload["medio_probatorio"], int(payload.get("rebate_usado", False)),
                        payload.get("resultado_rebate"),
                        json.dumps(payload.get("post_rejection_action"), ensure_ascii=False)
                        if payload.get("post_rejection_action") else None,
                    ),
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError("Ya existe feedback para esta decision") from exc

    def save_funnel_event(self, payload: dict[str, Any]) -> int:
        decision_id = payload["decision_id"]
        if not self.decision_exists(decision_id):
            raise KeyError(decision_id)
        allowed_previous = {
            "classified": set(),
            "displayed": {"classified"},
            "contacted": {"displayed"},
            "negotiated": {"contacted"},
            "rebate_used": {"negotiated"},
            "accepted": {"contacted", "negotiated", "rebate_used"},
            "rejected": {"contacted", "negotiated", "rebate_used"},
        }
        with self.connect() as connection:
            existing = {row["event_type"] for row in connection.execute(
                "SELECT event_type FROM funnel_events WHERE decision_id = ?", (decision_id,)
            )}
            event_type = payload["event_type"]
            if event_type in existing:
                raise ValueError(f"El evento {event_type} ya fue registrado")
            if event_type in {"accepted", "rejected"} and existing.intersection({"accepted", "rejected"}):
                raise ValueError("La decisión ya tiene un resultado terminal")
            required = allowed_previous[event_type]
            if required and not existing.intersection(required):
                raise ValueError(f"Transición inválida a {event_type}; eventos actuales: {sorted(existing)}")
            cursor = connection.execute(
                """INSERT INTO funnel_events
                (decision_id, created_at, event_type, channel, offer_id, proof_type, evidence_reference, rejection_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision_id, datetime.now(timezone.utc).isoformat(), event_type, payload.get("canal"),
                    payload.get("oferta_id"), payload.get("medio_probatorio"), payload.get("evidencia_referencia"),
                    payload.get("motivo_rechazo"),
                ),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def _decode_state_event(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item["changes_before"] = json.loads(item.pop("changes_before_json"))
        item["changes_after"] = json.loads(item.pop("changes_after_json"))
        return item

    def customer_state_version(self, cliente_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(state_version_after), 0) AS version FROM customer_state_events WHERE cliente_id=?",
                (cliente_id,),
            ).fetchone()
        return int(row["version"])

    def get_customer_event_by_idempotency(self, key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM customer_state_events WHERE idempotency_key=?", (key,)
            ).fetchone()
        return self._decode_state_event(row) if row is not None else None

    def get_customer_event(self, event_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM customer_state_events WHERE event_id=?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return self._decode_state_event(row)

    def list_customer_events(self, cliente_id: str, as_of: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM customer_state_events WHERE cliente_id=?"
        params: list[Any] = [cliente_id]
        if as_of is not None:
            query += " AND effective_at<=?"
            params.append(as_of)
        query += " ORDER BY effective_at, recorded_at, event_id"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._decode_state_event(row) for row in rows]

    def save_customer_state_event(
        self, payload: dict[str, Any], expected_state_version: int,
    ) -> tuple[dict[str, Any], bool]:
        """Append atomico con replay idempotente y control optimista."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM customer_state_events WHERE idempotency_key=?",
                (payload["idempotency_key"],),
            ).fetchone()
            if existing is not None:
                return self._decode_state_event(existing), True
            version = int(connection.execute(
                "SELECT COALESCE(MAX(state_version_after), 0) version FROM customer_state_events WHERE cliente_id=?",
                (payload["cliente_id"],),
            ).fetchone()["version"])
            if version != expected_state_version:
                raise StateVersionConflict(
                    f"Conflicto de version: esperada {expected_state_version}, vigente {version}"
                )
            payload = {**payload, "state_version_before": version, "state_version_after": version + 1}
            connection.execute(
                """INSERT INTO customer_state_events
                (event_id, cliente_id, event_type, effective_at, recorded_at, source, decision_id,
                 oferta_id, changes_before_json, changes_after_json, evidence_type, evidence_reference,
                 idempotency_key, correction_of_event_id, state_version_before, state_version_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload["event_id"], payload["cliente_id"], payload["event_type"],
                    payload["effective_at"], payload["recorded_at"], payload["source"],
                    payload.get("decision_id"), payload.get("oferta_id"),
                    json.dumps(payload.get("changes_before", {}), ensure_ascii=False),
                    json.dumps(payload.get("changes_after", {}), ensure_ascii=False),
                    payload.get("evidence_type"), payload.get("evidence_reference"),
                    payload["idempotency_key"], payload.get("correction_of_event_id"),
                    version, version + 1,
                ),
            )
        return payload, False

    def record_customer_event_rejection(
        self, cliente_id: str, idempotency_key: str, reason: str, detail: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO customer_event_rejections
                (recorded_at, cliente_id, idempotency_key, reason, detail)
                VALUES (?, ?, ?, ?, ?)""",
                (datetime.now(timezone.utc).isoformat(), cliente_id, idempotency_key, reason, detail),
            )

    def validate_activation_decision(self, decision_id: str, oferta_id: str, cliente_id: str) -> None:
        with self.connect() as connection:
            decision = connection.execute(
                "SELECT cliente_id FROM nbo_decisions WHERE decision_id=?", (decision_id,)
            ).fetchone()
            if decision is None:
                raise KeyError(decision_id)
            if decision["cliente_id"] != cliente_id:
                raise ValueError("La decision no pertenece al cliente")
            candidate = connection.execute(
                "SELECT 1 FROM nbo_candidates WHERE decision_id=? AND offer_id=?",
                (decision_id, oferta_id),
            ).fetchone()
            if candidate is None:
                raise ValueError("La oferta no pertenece a los candidatos de la decision")
            feedback = connection.execute(
                """SELECT 1 FROM feedback_events WHERE decision_id=?
                AND (final_result='aceptada' OR (rebate_used=1 AND rebate_result='aceptada'))""",
                (decision_id,),
            ).fetchone()
            funnel = connection.execute(
                "SELECT 1 FROM funnel_events WHERE decision_id=? AND event_type='accepted' AND offer_id=?",
                (decision_id, oferta_id),
            ).fetchone()
            if feedback is None and funnel is None:
                raise ValueError("La activacion requiere una aceptacion previa registrada")

    def operational_interactions(self, cliente_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Una fila por decision; feedback tiene prioridad y funnel completa los vacios."""
        query = "SELECT * FROM nbo_decisions"
        params: list[Any] = []
        if cliente_ids:
            query += f" WHERE cliente_id IN ({','.join('?' for _ in cliente_ids)})"
            params.extend(cliente_ids)
        with self.connect() as connection:
            decisions = connection.execute(query, params).fetchall()
            rows: list[dict[str, Any]] = []
            for decision in decisions:
                feedback = connection.execute(
                    "SELECT * FROM feedback_events WHERE decision_id=?", (decision["decision_id"],)
                ).fetchone()
                events = connection.execute(
                    "SELECT * FROM funnel_events WHERE decision_id=?", (decision["decision_id"],)
                ).fetchall()
                kinds = {event["event_type"] for event in events}
                terminal = None
                reason = None
                if feedback is not None:
                    terminal = feedback["final_result"]
                    reason = feedback["rejection_reason"]
                elif "accepted" in kinds:
                    terminal = "aceptada"
                elif "rejected" in kinds:
                    terminal = "rechazada"
                    rejected = next(event for event in events if event["event_type"] == "rejected")
                    reason = rejected["rejection_reason"]
                elif events and "contacted" not in kinds:
                    terminal = "no_contactado"
                contacted = terminal in {"aceptada", "rechazada"} or "contacted" in kinds
                rows.append({
                    "decision_id": decision["decision_id"], "cliente_id": decision["cliente_id"],
                    "oferta_id": decision["top_offer_id"], "canal": decision["top_channel"],
                    "created_at": decision["created_at"], "offered": True, "contacted": contacted,
                    "accepted": terminal == "aceptada", "rejected": terminal == "rechazada",
                    "no_contacted": terminal == "no_contactado", "rejection_reason": reason,
                    "state_snapshot_json": decision["state_snapshot_json"],
                })
        return rows

    def learning_readiness(self, thresholds: dict[str, int], last_training_at: str | None = None) -> dict[str, Any]:
        interactions = [row for row in self.operational_interactions() if row["accepted"] or row["rejected"] or row["no_contacted"]]
        channels: dict[str, int] = {}
        offers: dict[str, int] = {}
        stages: dict[str, int] = {}
        reasons: dict[str, int] = {}
        for row in interactions:
            channels[row["canal"]] = channels.get(row["canal"], 0) + 1
            offers[row["oferta_id"]] = offers.get(row["oferta_id"], 0) + 1
            try:
                stage = json.loads(row["state_snapshot_json"] or "{}").get("etapa_mt", "unknown")
            except json.JSONDecodeError:
                stage = "unknown"
            stages[stage] = stages.get(stage, 0) + 1
            if row["rejection_reason"]:
                reasons[row["rejection_reason"]] = reasons.get(row["rejection_reason"], 0) + 1
        now = datetime.now(timezone.utc)
        trained = datetime.fromisoformat(last_training_at.replace("Z", "+00:00")) if last_training_at else now
        if trained.tzinfo is None:
            trained = trained.replace(tzinfo=timezone.utc)
        values = {
            "feedback": len(interactions), "customers": len({row["cliente_id"] for row in interactions}),
            "channels": len(channels), "offers": len(offers),
        }
        failures = [key for key, minimum in thresholds.items() if values.get(key, 0) < int(minimum)]
        return {
            "status": "insufficient_data" if failures else "ready_for_challenger",
            "usable_feedback": values["feedback"], "unique_customers": values["customers"],
            "contacts": sum(row["contacted"] for row in interactions),
            "acceptances": sum(row["accepted"] for row in interactions),
            "rejections": sum(row["rejected"] for row in interactions),
            "coverage_by_channel": channels, "coverage_by_offer": offers,
            "coverage_by_mt_stage": stages, "rejection_reasons": reasons,
            "days_since_last_training": max((now - trained).days, 0), "thresholds": thresholds,
            "reasons": [f"{key}: {values.get(key, 0)} < {thresholds[key]}" for key in failures],
        }

    def business_metrics(self) -> dict[str, Any]:
        with self.connect() as connection:
            decisions = connection.execute("SELECT COUNT(*) n, AVG(p_acceptance) p_accept, AVG(p_sale) p_sale, AVG(score) score FROM nbo_decisions").fetchone()
            funnel = connection.execute("SELECT final_result, COUNT(*) n FROM feedback_events GROUP BY final_result").fetchall()
            mt = connection.execute("SELECT COUNT(*) n FROM nbo_decisions WHERE top_offer_id IN ('OF020','OF021','OF022')").fetchone()["n"]
            event_funnel = connection.execute("SELECT event_type, COUNT(*) n FROM funnel_events GROUP BY event_type").fetchall()
            recovery = connection.execute(
                "SELECT COUNT(*) n FROM feedback_events WHERE post_rejection_action_json IS NOT NULL"
            ).fetchone()["n"]
            experiments = connection.execute(
                """SELECT p.variant, COUNT(*) exposures,
                SUM(CASE WHEN EXISTS (
                    SELECT 1 FROM funnel_events e WHERE e.decision_id=p.decision_id AND e.event_type='contacted'
                ) THEN 1 ELSE 0 END) contacted,
                SUM(CASE WHEN f.final_result='aceptada' THEN 1 ELSE 0 END) accepted,
                SUM(CASE WHEN f.final_result='rechazada' THEN 1 ELSE 0 END) rejected,
                SUM(CASE WHEN f.rebate_used=1 THEN 1 ELSE 0 END) rebate_used
                FROM playbook_exposures p LEFT JOIN feedback_events f ON f.decision_id=p.decision_id
                GROUP BY p.variant"""
            ).fetchall()
            state_types = connection.execute(
                "SELECT event_type, COUNT(*) n FROM customer_state_events GROUP BY event_type"
            ).fetchall()
            state_rows = connection.execute(
                """SELECT cliente_id, decision_id, recorded_at, changes_before_json, changes_after_json
                FROM customer_state_events"""
            ).fetchall()
            mt_decisions = connection.execute(
                """SELECT cliente_id, created_at FROM nbo_decisions
                WHERE top_offer_id IN ('OF020','OF021','OF022') ORDER BY created_at"""
            ).fetchall()
            decision_times = {
                row["decision_id"]: row["created_at"]
                for row in connection.execute("SELECT decision_id, created_at FROM nbo_decisions")
            }
            recalculated = connection.execute(
                "SELECT COUNT(*) n FROM nbo_decisions WHERE state_version > 0"
            ).fetchone()["n"]
            activation_delays = connection.execute(
                """SELECT s.recorded_at activated_at, COALESCE(f.created_at, a.created_at) accepted_at
                FROM customer_state_events s
                LEFT JOIN feedback_events f ON f.decision_id=s.decision_id
                    AND (f.final_result='aceptada' OR f.rebate_result='aceptada')
                LEFT JOIN funnel_events a ON a.decision_id=s.decision_id AND a.event_type='accepted'
                WHERE s.event_type='product_activated' AND s.decision_id IS NOT NULL
                    AND COALESCE(f.created_at, a.created_at) IS NOT NULL"""
            ).fetchall()
            rejected_events = connection.execute(
                "SELECT reason, COUNT(*) n FROM customer_event_rejections GROUP BY reason"
            ).fetchall()
        delay_seconds = []
        for row in activation_delays:
            activated = datetime.fromisoformat(row["activated_at"].replace("Z", "+00:00"))
            accepted = datetime.fromisoformat(row["accepted_at"].replace("Z", "+00:00"))
            delay_seconds.append(max((activated - accepted).total_seconds(), 0.0))
        transitions: dict[str, int] = {}
        converted_clients: set[str] = set()
        eligibility_delays: list[float] = []
        mt_recommendation_delays: list[float] = []
        for row in state_rows:
            before = json.loads(row["changes_before_json"])
            after = json.loads(row["changes_after_json"])
            from_stage, to_stage = before.get("_mt_stage"), after.get("_mt_stage")
            if from_stage and to_stage and from_stage != to_stage:
                key = f"{from_stage}->{to_stage}"
                transitions[key] = transitions.get(key, 0) + 1
            if to_stage == "elegible_mt" and from_stage != "elegible_mt":
                converted_clients.add(row["cliente_id"])
                eligible_at = datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
                if row["decision_id"] in decision_times:
                    decided_at = datetime.fromisoformat(
                        decision_times[row["decision_id"]].replace("Z", "+00:00")
                    )
                    eligibility_delays.append(max((eligible_at - decided_at).total_seconds(), 0.0))
                later_mt = [
                    datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                    for item in mt_decisions if item["cliente_id"] == row["cliente_id"]
                    and datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")) >= eligible_at
                ]
                if later_mt:
                    mt_recommendation_delays.append(
                        max((min(later_mt) - eligible_at).total_seconds(), 0.0)
                    )
        return {
            "decisions": dict(decisions), "feedback_funnel": [dict(row) for row in funnel],
            "event_funnel": [dict(row) for row in event_funnel], "mt_recommendations": mt,
            "post_rejection_actions": recovery,
            "customer_state_events": [dict(row) for row in state_types],
            "customers_converted_to_mt_eligible": len(converted_clients),
            "recommendations_recalculated_after_activation": recalculated,
            "mt_stage_transitions": transitions,
            "average_acceptance_to_activation_seconds": (
                sum(delay_seconds) / len(delay_seconds) if delay_seconds else None
            ),
            "average_time_to_mt_eligibility_seconds": (
                sum(eligibility_delays) / len(eligibility_delays) if eligibility_delays else None
            ),
            "average_time_to_mt_recommendation_seconds": (
                sum(mt_recommendation_delays) / len(mt_recommendation_delays)
                if mt_recommendation_delays else None
            ),
            "rejected_customer_events": {row["reason"]: row["n"] for row in rejected_events},
            "playbook_experiment": {
                "interpretation": "descriptive_only",
                "variants": [dict(row) for row in experiments],
            },
        }
