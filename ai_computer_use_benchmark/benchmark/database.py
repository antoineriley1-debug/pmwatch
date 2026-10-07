"""Append-only run database. Failed attempts and difficult questions stay in
the dataset; there is no delete path (spec section 18)."""
from __future__ import annotations

import json
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    run_name TEXT,
    started_at TEXT,
    ended_at TEXT,
    status TEXT,
    config_json TEXT,
    config_hash TEXT,
    prompt_hash TEXT,
    model_identity_json TEXT,
    environment_json TEXT
);
CREATE TABLE IF NOT EXISTS questions (
    run_id TEXT,
    seq INTEGER,
    question_key TEXT,
    question_number INTEGER,
    question_type TEXT,
    question_text TEXT,
    options_json TEXT,
    intended_answer_json TEXT,
    selected_answer_json TEXT,
    confidence INTEGER,
    reasoning TEXT,
    outcome TEXT,
    duration_s REAL,
    max_attempts INTEGER,
    multiple_attempts INTEGER,
    navigation_retries INTEGER,
    failure_categories_json TEXT,
    milestones_json TEXT,
    reviews_json TEXT,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    ts TEXT,
    event_type TEXT,
    question_seq INTEGER,
    category TEXT,
    data_json TEXT
);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    ts TEXT,
    question_seq INTEGER,
    purpose TEXT,
    target TEXT,
    attempts INTEGER,
    success INTEGER,
    first_attempt_success INTEGER,
    recovery_used INTEGER,
    points_json TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS screens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    ts TEXT,
    label TEXT,
    question_seq INTEGER,
    states TEXT,
    parse_ok INTEGER,
    screenshot_path TEXT,
    analysis_json TEXT
);
CREATE TABLE IF NOT EXISTS model_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    ts TEXT,
    purpose TEXT,
    model_requested TEXT,
    model_served TEXT,
    latency_s REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    stop_reason TEXT,
    error TEXT
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def insert(self, table: str, row: dict) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        values = [json.dumps(v, default=str) if isinstance(v, (dict, list)) else v for v in row.values()]
        with self._lock:
            self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", values)
            self.conn.commit()

    def finish_run(self, run_id: str, ended_at: str, status: str, model_identity: dict) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE runs SET ended_at = ?, status = ?, model_identity_json = ? WHERE run_id = ?",
                (ended_at, status, json.dumps(model_identity, default=str), run_id))
            self.conn.commit()

    def rows(self, table: str, run_id: str) -> list[dict]:
        with self._lock:
            cur = self.conn.execute(f"SELECT * FROM {table} WHERE run_id = ?", (run_id,))
            return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        with self._lock:
            self.conn.close()
