"""Shared helpers for Northline CRM CLIs."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def db_path() -> Path:
    raw = os.getenv("NORTHLINE_DB_PATH", "data/northline_crm.sqlite3")
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def external_key(name: str, city: str | None, phone: str | None) -> str:
    base = f"{(name or '').strip().lower()}|{(city or '').strip().lower()}|{(phone or '').strip()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def load_weights() -> dict:
    path = ROOT / "config" / "scoring_weights.json"
    return json.loads(path.read_text(encoding="utf-8"))


def log_run(workflow: str, args: dict, result: dict, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO agent_runs (workflow, args_json, result_json, status) VALUES (?, ?, ?, ?)",
            (workflow, json.dumps(args), json.dumps(result), status),
        )
        conn.commit()
