"""
SQLite Database Storage Layer for ChurchMix.
Provides persistent audit logging, snapshot vault, and acoustic measurement history.
"""
from typing import Dict, Any, List, Optional
import sqlite3
import json
import time
import os
import hashlib


class ChurchMixDatabase:
    """Manages SQLite storage for immutable audit events, snapshots and measurements."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Default to data/churchmix.db
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            data_dir = os.path.join(root, "data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "churchmix.db")

        self.db_path = db_path
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        """Create required tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Snapshots Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mixer_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE,
                    state_json TEXT NOT NULL,
                    captured_at REAL NOT NULL,
                    iso_time TEXT NOT NULL,
                    author TEXT NOT NULL,
                    note TEXT
                )
            """)

            # 2. Audit Events Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    proposal_id TEXT,
                    status TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    immutable_hash TEXT NOT NULL
                )
            """)

            # 3. Acoustic Measurements Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    name TEXT NOT NULL,
                    position TEXT NOT NULL,
                    delay_ms REAL NOT NULL,
                    coherence_avg REAL NOT NULL,
                    rule_enforced TEXT NOT NULL,
                    result_json TEXT NOT NULL
                )
            """)

            # 4. Subjective A/B Listening Tests Table (Master Plan Section 3.4)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listening_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    iso_time TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    proposal_id TEXT,
                    target_channel INTEGER NOT NULL,
                    channel_name TEXT NOT NULL,
                    overall_mos REAL NOT NULL,
                    recommendation TEXT NOT NULL,
                    criteria_json TEXT NOT NULL,
                    strengths_json TEXT NOT NULL,
                    weaknesses_json TEXT NOT NULL,
                    advice_vi TEXT NOT NULL,
                    loudness_compensation_db REAL NOT NULL,
                    is_blind_test INTEGER NOT NULL
                )
            """)
            conn.commit()

    def save_snapshot(
        self,
        sha256: str,
        state_dict: Dict[str, Any],
        mixer_id: str = "X32_Compact",
        iso_time: Optional[str] = None,
        author: str = "System",
        note: str = "",
    ) -> int:
        """Persist a mixer snapshot with its SHA-256 integrity hash."""
        now = time.time()
        iso = iso_time or time.strftime("%Y-%m-%dT%H:%M:%S%z")
        json_data = json.dumps(state_dict)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO snapshots 
                (mixer_id, sha256, state_json, captured_at, iso_time, author, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (mixer_id, sha256, json_data, now, iso, author, note))
            conn.commit()
            return cursor.lastrowid

    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        """Retrieve most recent saved snapshot."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "mixer_id": row["mixer_id"],
                    "sha256": row["sha256"],
                    "captured_at": row["captured_at"],
                    "iso_time": row["iso_time"],
                    "author": row["author"],
                    "note": row["note"],
                }
            return None

    def get_snapshots(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve list of saved snapshots (without full state_json to keep it fast)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, mixer_id, sha256, captured_at, iso_time, author, note 
                FROM snapshots 
                ORDER BY id DESC 
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "mixer_id": r["mixer_id"],
                    "sha256": r["sha256"],
                    "captured_at": r["captured_at"],
                    "iso_time": r["iso_time"],
                    "author": r["author"],
                    "note": r["note"],
                }
                for r in rows
            ]

    def get_snapshot_by_id(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve full snapshot including state parameters by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "mixer_id": row["mixer_id"],
                    "sha256": row["sha256"],
                    "captured_at": row["captured_at"],
                    "iso_time": row["iso_time"],
                    "author": row["author"],
                    "note": row["note"],
                    "state": json.loads(row["state_json"]),
                }
            return None

    def delete_snapshot(self, snapshot_id: int) -> bool:
        """Delete a snapshot by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
            conn.commit()
            return cursor.rowcount > 0

    def save_audit_event(
        self,
        actor: str,
        action: str,
        proposal_id: Optional[str] = None,
        status: str = "COMMITTED",
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Save a transaction/action event to immutable audit log with cryptographic hash."""
        now = time.time()
        details_str = json.dumps(details or {})
        # Compute immutable event hash: sha256(now + actor + action + proposal_id + details)
        hash_payload = f"{now}|{actor}|{action}|{proposal_id}|{status}|{details_str}".encode("utf-8")
        event_hash = hashlib.sha256(hash_payload).hexdigest()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO audit_events 
                (timestamp, actor, action, proposal_id, status, details_json, immutable_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (now, actor, action, proposal_id, status, details_str, event_hash))
            conn.commit()
            return cursor.lastrowid

    def get_recent_audit_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent audit events for UI dashboard and compliance."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            events = []
            for r in rows:
                events.append({
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "iso_time": time.strftime("%H:%M:%S", time.localtime(r["timestamp"])),
                    "actor": r["actor"],
                    "action": r["action"],
                    "proposal_id": r["proposal_id"],
                    "status": r["status"],
                    "details": json.loads(r["details_json"]),
                    "immutable_hash": r["immutable_hash"][:12],
                })
            return events

    def get_audit_trail(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Alias for get_recent_audit_events."""
        return self.get_recent_audit_events(limit=limit)

    def save_measurement(
        self,
        name: str,
        position: str,
        delay_ms: float,
        coherence_avg: float,
        rule_enforced: str,
        result_data: Dict[str, Any],
    ) -> int:
        """Persist an acoustic measurement session."""
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO measurements 
                (timestamp, name, position, delay_ms, coherence_avg, rule_enforced, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (now, name, position, delay_ms, coherence_avg, rule_enforced, json.dumps(result_data)))
            conn.commit()
            return cursor.lastrowid

    def get_measurements(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List acoustic measurements history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM measurements ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            items = []
            for r in rows:
                items.append({
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "name": r["name"],
                    "position": r["position"],
                    "delay_ms": r["delay_ms"],
                    "coherence_avg": r["coherence_avg"],
                    "rule_enforced": r["rule_enforced"],
                })
            return items

    def save_listening_test(
        self,
        evaluation_data: Dict[str, Any],
    ) -> int:
        """Persist a subjective A/B listening evaluation into SQLite."""
        now = evaluation_data.get("created_at", time.time())
        iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO listening_tests
                (timestamp, iso_time, operator, proposal_id, target_channel, channel_name,
                 overall_mos, recommendation, criteria_json, strengths_json, weaknesses_json,
                 advice_vi, loudness_compensation_db, is_blind_test)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now,
                iso,
                evaluation_data.get("operator", "Operator"),
                evaluation_data.get("proposal_id"),
                evaluation_data.get("target_channel", 1),
                evaluation_data.get("channel_name", "Channel"),
                float(evaluation_data.get("overall_mos", 0.0)),
                evaluation_data.get("recommendation", "UNKNOWN"),
                json.dumps(evaluation_data.get("criteria", {})),
                json.dumps(evaluation_data.get("strengths_vi", [])),
                json.dumps(evaluation_data.get("weaknesses_vi", [])),
                evaluation_data.get("advice_vi", ""),
                float(evaluation_data.get("loudness_compensation_db", 0.0)),
                1 if evaluation_data.get("is_blind_test") else 0,
            ))
            conn.commit()
            return cursor.lastrowid

    def list_listening_tests(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent subjective A/B listening evaluations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM listening_tests ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            items = []
            for r in rows:
                items.append({
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "iso_time": r["iso_time"],
                    "operator": r["operator"],
                    "proposal_id": r["proposal_id"],
                    "target_channel": r["target_channel"],
                    "channel_name": r["channel_name"],
                    "overall_mos": r["overall_mos"],
                    "recommendation": r["recommendation"],
                    "criteria": json.loads(r["criteria_json"]),
                    "strengths_vi": json.loads(r["strengths_json"]),
                    "weaknesses_vi": json.loads(r["weaknesses_json"]),
                    "advice_vi": r["advice_vi"],
                    "loudness_compensation_db": r["loudness_compensation_db"],
                    "is_blind_test": bool(r["is_blind_test"]),
                })
            return items

