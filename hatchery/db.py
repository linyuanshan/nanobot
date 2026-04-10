"""SQLite persistence for the hatchery service."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


class HatcheryRepository:
    """Thin SQLite repository with JSON columns."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.database_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def ping(self) -> bool:
        try:
            self._conn.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            return False
        return True

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pool_state (
                    pool_id TEXT PRIMARY KEY,
                    site_id TEXT NOT NULL,
                    workshop_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    telemetry_json TEXT NOT NULL,
                    bio_json TEXT NOT NULL,
                    assessment_level TEXT NOT NULL,
                    assessment_reasons_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS telemetry_events (
                    event_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    pool_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    topic TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS perception_events (
                    event_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    pool_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    topic TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS action_plans (
                    plan_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    pool_id TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    decision_explanation TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    pool_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    timeout_at TEXT NOT NULL,
                    last_reminded_at TEXT,
                    operator TEXT NOT NULL,
                    reason TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS commands (
                    command_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    trace_id TEXT NOT NULL,
                    site_id TEXT NOT NULL,
                    workshop_id TEXT NOT NULL,
                    pool_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    effective_action_type TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    effective_params_json TEXT NOT NULL,
                    preconditions_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_code TEXT NOT NULL,
                    approval_id TEXT,
                    deadline_sec INTEGER NOT NULL,
                    degrade_policy TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    receipt_json TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS command_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_id TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS verification_results (
                    command_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    verified_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    mode TEXT,
                    site_id TEXT,
                    workshop_id TEXT,
                    pool_id TEXT,
                    receipt_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column("commands", "site_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("commands", "workshop_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column("audits", "mode", "TEXT")
            self._ensure_column("audits", "site_id", "TEXT")
            self._ensure_column("audits", "workshop_id", "TEXT")
            self._ensure_column("audits", "pool_id", "TEXT")
            self._conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _dump(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)

    def _load(self, value: str | None) -> Any:
        if not value:
            return {}
        return json.loads(value)

    def upsert_pool_state(
        self,
        *,
        pool_id: str,
        site_id: str,
        workshop_id: str,
        mode: str,
        telemetry: dict[str, Any],
        bio: dict[str, Any],
        assessment_level: str,
        assessment_reasons: list[str],
        updated_at: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO pool_state (
                    pool_id, site_id, workshop_id, mode, telemetry_json, bio_json,
                    assessment_level, assessment_reasons_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pool_id) DO UPDATE SET
                    site_id=excluded.site_id,
                    workshop_id=excluded.workshop_id,
                    mode=excluded.mode,
                    telemetry_json=excluded.telemetry_json,
                    bio_json=excluded.bio_json,
                    assessment_level=excluded.assessment_level,
                    assessment_reasons_json=excluded.assessment_reasons_json,
                    updated_at=excluded.updated_at
                """,
                (
                    pool_id,
                    site_id,
                    workshop_id,
                    mode,
                    self._dump(telemetry),
                    self._dump(bio),
                    assessment_level,
                    self._dump(assessment_reasons),
                    updated_at,
                ),
            )
            self._conn.commit()

    def get_pool_state(self, pool_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM pool_state WHERE pool_id = ?", (pool_id,)).fetchone()
        if not row:
            return None
        return {
            "pool_id": row["pool_id"],
            "site_id": row["site_id"],
            "workshop_id": row["workshop_id"],
            "mode": row["mode"],
            "telemetry": self._load(row["telemetry_json"]),
            "bio": self._load(row["bio_json"]),
            "assessment_level": row["assessment_level"],
            "assessment_reasons": self._load(row["assessment_reasons_json"]),
            "updated_at": row["updated_at"],
        }

    def save_event(
        self,
        *,
        table: str,
        event_id: str,
        trace_id: str,
        pool_id: str,
        event_type: str,
        payload: dict[str, Any],
        ts: str,
        topic: str,
    ) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                f"""
                INSERT OR IGNORE INTO {table} (
                    event_id, trace_id, pool_id, event_type, payload_json, ts, topic
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, trace_id, pool_id, event_type, self._dump(payload), ts, topic),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def save_action_plan(self, plan: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO action_plans (
                    plan_id, trace_id, pool_id, risk_level, decision_explanation,
                    actions_json, model_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan["plan_id"],
                    plan["trace_id"],
                    plan["pool_id"],
                    plan["risk_level"],
                    plan["decision_explanation"],
                    self._dump(plan["actions"]),
                    plan["model_version"],
                    plan["created_at"],
                ),
            )
            self._conn.commit()

    def insert_command(self, command: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO commands (
                    command_id, idempotency_key, trace_id, site_id, workshop_id, pool_id,
                    mode, action_type, effective_action_type, params_json,
                    effective_params_json, preconditions_json, risk_level, status,
                    result_code, approval_id, deadline_sec, degrade_policy, dry_run,
                    receipt_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command["command_id"],
                    command["idempotency_key"],
                    command["trace_id"],
                    command["site_id"],
                    command["workshop_id"],
                    command["pool_id"],
                    command["mode"],
                    command["action_type"],
                    command["effective_action_type"],
                    self._dump(command["params"]),
                    self._dump(command["effective_params"]),
                    self._dump(command["preconditions"]),
                    command["risk_level"],
                    command["status"],
                    command["result_code"],
                    command.get("approval_id"),
                    command["deadline_sec"],
                    command["degrade_policy"],
                    1 if command["dry_run"] else 0,
                    self._dump(command.get("receipt")),
                    command["updated_at"],
                ),
            )
            self._conn.commit()

    def update_command(self, command_id: str, **fields: Any) -> None:
        assignments = []
        values = []
        for key, value in fields.items():
            if key.endswith("_json"):
                assignments.append(f"{key} = ?")
                values.append(self._dump(value))
            elif key == "receipt":
                assignments.append("receipt_json = ?")
                values.append(self._dump(value))
            elif key in {"params", "effective_params", "preconditions"}:
                assignments.append(f"{key}_json = ?")
                values.append(self._dump(value))
            else:
                assignments.append(f"{key} = ?")
                values.append(value)
        values.append(command_id)
        with self._lock:
            self._conn.execute(f"UPDATE commands SET {', '.join(assignments)} WHERE command_id = ?", tuple(values))
            self._conn.commit()

    def get_command_by_id(self, command_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM commands WHERE command_id = ?", (command_id,)).fetchone()
        if not row:
            return None
        return self._row_to_command(row)

    def get_command_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM commands WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if not row:
            return None
        return self._row_to_command(row)

    def list_commands(
        self,
        *,
        pool_id: str | None = None,
        status: str | None = None,
        risk_level: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = []
        values: list[Any] = []
        if pool_id:
            clauses.append("pool_id = ?")
            values.append(pool_id)
        if status:
            clauses.append("status = ?")
            values.append(status)
        if risk_level:
            clauses.append("risk_level = ?")
            values.append(risk_level)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM commands {where_clause} ORDER BY updated_at DESC LIMIT ?",
            (*values, limit),
        ).fetchall()
        return [self._row_to_command(row) for row in rows]

    def _row_to_command(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "command_id": row["command_id"],
            "idempotency_key": row["idempotency_key"],
            "trace_id": row["trace_id"],
            "site_id": row["site_id"],
            "workshop_id": row["workshop_id"],
            "pool_id": row["pool_id"],
            "mode": row["mode"],
            "action_type": row["action_type"],
            "effective_action_type": row["effective_action_type"],
            "params": self._load(row["params_json"]),
            "effective_params": self._load(row["effective_params_json"]),
            "preconditions": self._load(row["preconditions_json"]),
            "risk_level": row["risk_level"],
            "status": row["status"],
            "result_code": row["result_code"],
            "approval_id": row["approval_id"],
            "deadline_sec": row["deadline_sec"],
            "degrade_policy": row["degrade_policy"],
            "dry_run": bool(row["dry_run"]),
            "receipt": self._load(row["receipt_json"]) if row["receipt_json"] else None,
            "updated_at": row["updated_at"],
        }

    def insert_transition(
        self,
        *,
        command_id: str,
        from_status: str | None,
        to_status: str,
        reason: str,
        created_at: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO command_transitions (
                    command_id, from_status, to_status, reason, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (command_id, from_status, to_status, reason, created_at or iso_now()),
            )
            self._conn.commit()

    def list_transitions(self, command_id: str) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT to_status FROM command_transitions
            WHERE command_id = ?
            ORDER BY id ASC
            """,
            (command_id,),
        ).fetchall()
        return [row["to_status"] for row in rows]

    def list_transition_records(self, command_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT from_status, to_status, reason, created_at FROM command_transitions
            WHERE command_id = ?
            ORDER BY id ASC
            """,
            (command_id,),
        ).fetchall()
        return [
            {
                "from_status": row["from_status"],
                "to_status": row["to_status"],
                "reason": row["reason"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def insert_approval(self, approval: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO approvals (
                    approval_id, command_id, trace_id, pool_id, provider, status, decision,
                    requested_at, remind_at, timeout_at, last_reminded_at, operator, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval["approval_id"],
                    approval["command_id"],
                    approval["trace_id"],
                    approval["pool_id"],
                    approval["provider"],
                    approval["status"],
                    approval["decision"],
                    approval["requested_at"],
                    approval["remind_at"],
                    approval["timeout_at"],
                    approval.get("last_reminded_at"),
                    approval["operator"],
                    approval["reason"],
                ),
            )
            self._conn.commit()

    def update_approval(self, approval_id: str, **fields: Any) -> None:
        assignments = [f"{key} = ?" for key in fields]
        values = list(fields.values()) + [approval_id]
        with self._lock:
            self._conn.execute(f"UPDATE approvals SET {', '.join(assignments)} WHERE approval_id = ?", tuple(values))
            self._conn.commit()

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        if not row:
            return None
        return dict(row)

    def list_due_pending_approvals(self, now_iso: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM approvals WHERE status = 'PendingApproval' AND timeout_at <= ?",
            (now_iso,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_pending_reminders(self, now_iso: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM approvals
            WHERE status = 'PendingApproval'
              AND remind_at <= ?
              AND last_reminded_at IS NULL
            """,
            (now_iso,),
        ).fetchall()
        return [dict(row) for row in rows]

    def count_approvals_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS count FROM approvals GROUP BY status"
        ).fetchall()
        return {row["status"]: row["count"] for row in rows}

    def count_commands_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS count FROM commands GROUP BY status"
        ).fetchall()
        return {row["status"]: row["count"] for row in rows}

    def count_commands_total(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS count FROM commands").fetchone()
        return int(row["count"])

    def insert_verification(self, command_id: str, status: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO verification_results (command_id, status, payload_json, verified_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(command_id) DO UPDATE SET
                    status=excluded.status,
                    payload_json=excluded.payload_json,
                    verified_at=excluded.verified_at
                """,
                (command_id, status, self._dump(payload), iso_now()),
            )
            self._conn.commit()

    def insert_audit(
        self,
        *,
        trace_id: str,
        event_type: str,
        reason: str,
        operator: str,
        model_version: str,
        receipt: dict[str, Any],
        payload: dict[str, Any],
        mode: str | None = None,
        site_id: str | None = None,
        workshop_id: str | None = None,
        pool_id: str | None = None,
    ) -> str:
        created_at = iso_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO audits (
                    trace_id, event_type, reason, operator, model_version,
                    mode, site_id, workshop_id, pool_id, receipt_json, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    event_type,
                    reason,
                    operator,
                    model_version,
                    mode,
                    site_id,
                    workshop_id,
                    pool_id,
                    self._dump(receipt),
                    self._dump(payload),
                    created_at,
                ),
            )
            self._conn.commit()
        return created_at

    def list_audits(
        self,
        *,
        trace_id: str | None = None,
        pool_id: str | None = None,
        event_type: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        values: list[Any] = []
        if trace_id:
            clauses.append("trace_id = ?")
            values.append(trace_id)
        if pool_id:
            clauses.append("pool_id = ?")
            values.append(pool_id)
        if event_type:
            clauses.append("event_type = ?")
            values.append(event_type)
        if from_ts:
            clauses.append("created_at >= ?")
            values.append(from_ts)
        if to_ts:
            clauses.append("created_at <= ?")
            values.append(to_ts)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM audits {where_clause} ORDER BY id ASC",
            tuple(values),
        ).fetchall()
        results = []
        for row in rows:
            results.append(
                {
                    "trace_id": row["trace_id"],
                    "event_type": row["event_type"],
                    "reason": row["reason"],
                    "operator": row["operator"],
                    "model_version": row["model_version"],
                    "mode": row["mode"],
                    "site_id": row["site_id"],
                    "workshop_id": row["workshop_id"],
                    "pool_id": row["pool_id"],
                    "receipt": self._load(row["receipt_json"]),
                    "payload": self._load(row["payload_json"]),
                    "created_at": row["created_at"],
                }
            )
        return results
