from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .events import ScanEvent


class SessionStore:
    """Thread-safe SQLite persistence for scan sessions and typed events."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.path), check_same_thread=False, timeout=10.0
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._migrate()
            self.mark_running_as_interrupted()

    def _migrate(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS scans (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                config_json TEXT NOT NULL,
                stats_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(scan_id) REFERENCES scans(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_events_scan_seq
                ON events(scan_id, seq);
            CREATE TABLE IF NOT EXISTS entities (
                scan_id TEXT NOT NULL,
                id TEXT NOT NULL,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                parent_id TEXT,
                status TEXT NOT NULL,
                data_json TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(scan_id, id),
                FOREIGN KEY(scan_id) REFERENCES scans(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_entities_scan_type
                ON entities(scan_id, type);
            CREATE TABLE IF NOT EXISTS relationships (
                scan_id TEXT NOT NULL,
                id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(scan_id, id),
                FOREIGN KEY(scan_id) REFERENCES scans(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS activities (
                scan_id TEXT NOT NULL,
                id TEXT NOT NULL,
                operation TEXT NOT NULL,
                target TEXT NOT NULL,
                detail TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                worker TEXT NOT NULL,
                data_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                PRIMARY KEY(scan_id, id),
                FOREIGN KEY(scan_id) REFERENCES scans(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_activities_scan_status
                ON activities(scan_id, status, updated_at);
            """
        )
        self._connection.commit()

    @staticmethod
    def _dumps(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _loads(value: str) -> Any:
        return json.loads(value)

    def create_scan(
        self, scan_id: str, config: dict[str, Any], timestamp: str
    ) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO scans(id,status,config_json,stats_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?)
                """,
                (scan_id, "queued", self._dumps(config), "{}", timestamp, timestamp),
            )
            self._connection.commit()

    def update_scan(
        self,
        scan_id: str,
        *,
        status: str | None = None,
        stats: dict[str, Any] | None = None,
        error: str | None = None,
        timestamp: str,
    ) -> None:
        with self._lock:
            current = self._connection.execute(
                "SELECT status,stats_json,error FROM scans WHERE id=?",
                (scan_id,),
            ).fetchone()
            if current is None:
                return
            selected_status = status if status is not None else current["status"]
            selected_stats = (
                self._dumps(stats) if stats is not None else current["stats_json"]
            )
            selected_error = error[:2000] if error is not None else current["error"]
            self._connection.execute(
                """
                UPDATE scans
                SET status=?, stats_json=?, error=?, updated_at=?
                WHERE id=?
                """,
                (
                    selected_status,
                    selected_stats,
                    selected_error,
                    timestamp,
                    scan_id,
                ),
            )
            self._connection.commit()

    def record_event(self, event: ScanEvent) -> int:
        payload = event.payload
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO events(scan_id,event_type,timestamp,payload_json)
                VALUES(?,?,?,?)
                """,
                (
                    event.scan_id,
                    event.event_type,
                    event.timestamp,
                    self._dumps(payload),
                ),
            )
            entity = payload.get("entity")
            if isinstance(entity, dict):
                self._upsert_entity(event, entity)
            relationship = payload.get("relationship")
            if isinstance(relationship, dict):
                self._upsert_relationship(event, relationship)
            activity = payload.get("activity")
            if isinstance(activity, dict):
                self._upsert_activity(event, activity)
            self._connection.execute(
                "UPDATE scans SET updated_at=? WHERE id=?",
                (event.timestamp, event.scan_id),
            )
            self._connection.commit()
            return int(cursor.lastrowid)

    def _upsert_entity(self, event: ScanEvent, entity: dict[str, Any]) -> None:
        required = {"id", "type", "name", "status"}
        if not required.issubset(entity):
            return
        self._connection.execute(
            """
            INSERT INTO entities(
                scan_id,id,type,name,parent_id,status,data_json,discovered_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(scan_id,id) DO UPDATE SET
                type=excluded.type,
                name=excluded.name,
                parent_id=excluded.parent_id,
                status=excluded.status,
                data_json=excluded.data_json,
                updated_at=excluded.updated_at
            """,
            (
                event.scan_id,
                str(entity["id"]),
                str(entity["type"]),
                str(entity["name"]),
                entity.get("parent_id"),
                str(entity["status"]),
                self._dumps(entity.get("data", {})),
                event.timestamp,
                event.timestamp,
            ),
        )

    def _upsert_relationship(
        self, event: ScanEvent, relationship: dict[str, Any]
    ) -> None:
        required = {"id", "source_id", "target_id", "kind"}
        if not required.issubset(relationship):
            return
        self._connection.execute(
            """
            INSERT INTO relationships(
                scan_id,id,source_id,target_id,kind,created_at
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(scan_id,id) DO NOTHING
            """,
            (
                event.scan_id,
                str(relationship["id"]),
                str(relationship["source_id"]),
                str(relationship["target_id"]),
                str(relationship["kind"]),
                event.timestamp,
            ),
        )

    def _upsert_activity(self, event: ScanEvent, activity: dict[str, Any]) -> None:
        required = {"id", "operation", "target", "status", "worker"}
        if not required.issubset(activity):
            return
        status = str(activity["status"])
        completed_at = (
            event.timestamp
            if status in {"completed", "failed", "cancelled"}
            else None
        )
        self._connection.execute(
            """
            INSERT INTO activities(
                scan_id,id,operation,target,detail,kind,status,worker,data_json,
                started_at,updated_at,completed_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(scan_id,id) DO UPDATE SET
                operation=excluded.operation,
                target=excluded.target,
                detail=excluded.detail,
                kind=excluded.kind,
                status=excluded.status,
                worker=excluded.worker,
                data_json=excluded.data_json,
                updated_at=excluded.updated_at,
                completed_at=COALESCE(excluded.completed_at,activities.completed_at)
            """,
            (
                event.scan_id,
                str(activity["id"]),
                str(activity["operation"]),
                str(activity["target"]),
                str(activity.get("detail", "")),
                str(activity.get("kind", "extraction")),
                status,
                str(activity["worker"]),
                self._dumps(activity),
                event.timestamp,
                event.timestamp,
                completed_at,
            ),
        )

    def mark_running_as_interrupted(self) -> None:
        with self._lock:
            self._connection.execute(
                """
                UPDATE scans SET status='interrupted'
                WHERE status IN ('queued','running','paused','stopping')
                """
            )
            self._connection.commit()

    def list_scans(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id,status,config_json,stats_json,error,created_at,updated_at
                FROM scans ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._scan_row(row) for row in rows]

    def get_scan(self, scan_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT id,status,config_json,stats_json,error,created_at,updated_at
                FROM scans WHERE id=?
                """,
                (scan_id,),
            ).fetchone()
        return self._scan_row(row) if row is not None else None

    def _scan_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "status": row["status"],
            "config": self._loads(row["config_json"]),
            "stats": self._loads(row["stats_json"]),
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_events(
        self, scan_id: str, *, after: int = 0, limit: int = 1000
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT seq,event_type,timestamp,payload_json
                FROM events WHERE scan_id=? AND seq>?
                ORDER BY seq LIMIT ?
                """,
                (scan_id, after, limit),
            ).fetchall()
        return [
            {
                "seq": row["seq"],
                "event": row["event_type"],
                "scan_id": scan_id,
                "timestamp": row["timestamp"],
                "payload": self._loads(row["payload_json"]),
            }
            for row in rows
        ]

    def get_activities(self, scan_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id,operation,target,detail,kind,status,worker,data_json,
                       started_at,updated_at,completed_at
                FROM activities WHERE scan_id=?
                ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END,
                         updated_at DESC LIMIT ?
                """,
                (scan_id, limit),
            ).fetchall()
        return [
            {
                **self._loads(row["data_json"]),
                "id": row["id"],
                "operation": row["operation"],
                "target": row["target"],
                "detail": row["detail"],
                "kind": row["kind"],
                "status": row["status"],
                "worker": row["worker"],
                "started_at": row["started_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
            }
            for row in rows
        ]

    def snapshot(self, scan_id: str) -> dict[str, Any] | None:
        scan = self.get_scan(scan_id)
        if scan is None:
            return None
        with self._lock:
            entity_rows = self._connection.execute(
                """
                SELECT id,type,name,parent_id,status,data_json,discovered_at,updated_at
                FROM entities WHERE scan_id=?
                ORDER BY CASE type
                    WHEN 'schema' THEN 1 WHEN 'table' THEN 2 WHEN 'column' THEN 3
                    WHEN 'row' THEN 4 WHEN 'cell' THEN 5 ELSE 9 END,
                    discovered_at,id
                """,
                (scan_id,),
            ).fetchall()
            relation_rows = self._connection.execute(
                """
                SELECT id,source_id,target_id,kind,created_at
                FROM relationships WHERE scan_id=? ORDER BY created_at,id
                """,
                (scan_id,),
            ).fetchall()
        entities = [
            {
                "id": row["id"],
                "type": row["type"],
                "name": row["name"],
                "parent_id": row["parent_id"],
                "status": row["status"],
                "data": self._loads(row["data_json"]),
                "discovered_at": row["discovered_at"],
                "updated_at": row["updated_at"],
            }
            for row in entity_rows
        ]
        relationships = [dict(row) for row in relation_rows]
        counts: dict[str, int] = {}
        for entity in entities:
            counts[entity["type"]] = counts.get(entity["type"], 0) + 1
        return {
            "scan": scan,
            "entities": entities,
            "relationships": relationships,
            "activities": self.get_activities(scan_id),
            "counts": counts,
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()
