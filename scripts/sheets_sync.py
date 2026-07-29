#!/usr/bin/env python3
"""Optional Google Sheets sync via gog (exports scored queue)."""
from __future__ import annotations

import argparse
import csv
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import connect, emit, log_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=int, default=55)
    parser.add_argument("--csv-only", action="store_true")
    args = parser.parse_args()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "business_name", "category", "metro", "website_status", "score", "status", "email"])
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, business_name, category, metro, website_status, score, status, email
            FROM leads WHERE score >= ? ORDER BY score DESC
            """,
            (args.min_score,),
        ).fetchall()
        for r in rows:
            writer.writerow([r["id"], r["business_name"], r["category"], r["metro"], r["website_status"], r["score"], r["status"], r["email"]])

    csv_text = buf.getvalue()
    sheet_id = os.getenv("GOG_SHEET_ID", "")
    synced = False
    note = "csv_only"
    if not args.csv_only and sheet_id and shutil.which("gog"):
        # Placeholder hook — operators wire the exact gog sheets update command for their build.
        note = "gog_present_configure_sheets_update"
        synced = False

    result = {
        "ok": True,
        "rows": len(rows),
        "sheet_id": sheet_id or None,
        "synced": synced,
        "note": note,
        "csv_preview_lines": csv_text.splitlines()[:6],
    }
    log_run("sheets_sync", vars(args), result, "ok")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
