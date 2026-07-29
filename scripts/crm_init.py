#!/usr/bin/env python3
"""Initialize / migrate the Northline SQL CRM."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, connect, db_path, emit  # noqa: E402


def main() -> int:
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    with connect() as conn:
        conn.executescript(schema)
        conn.commit()
    emit({"ok": True, "db": str(db_path()), "action": "crm_init"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
