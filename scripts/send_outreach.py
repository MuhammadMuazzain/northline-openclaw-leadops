#!/usr/bin/env python3
"""
Send or dry-run outreach for drafted events.

Real send path shells out to `gog gmail send` when --execute is passed.
Default is dry-run JSON so Lobster approval can gate the execute step.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import connect, emit, log_run  # noqa: E402


def send_via_gog(to: str, subject: str, body: str) -> tuple[bool, str]:
    if not shutil.which("gog"):
        return False, "gog_not_installed"
    # Interface varies by gog build; keep as a documented hook.
    cmd = ["gog", "gmail", "send", "--to", to, "--subject", subject, "--body", body]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return True, (proc.stdout or "").strip()[:500]
        return False, (proc.stderr or proc.stdout or "gog_failed")[:500]
    except Exception as e:
        return False, str(e)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--execute", action="store_true", help="Actually send via gog")
    parser.add_argument("--stdin-json", action="store_true", help="Optional filter payload from stdin")
    args = parser.parse_args()

    if args.stdin_json:
        try:
            json.load(sys.stdin)
        except Exception:
            pass

    results = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT e.id AS event_id, e.subject, e.body, e.template_id,
                   l.id AS lead_id, l.email, l.business_name
            FROM outreach_events e
            JOIN leads l ON l.id = e.lead_id
            WHERE e.status = 'drafted'
            ORDER BY e.created_at ASC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()

        for row in rows:
            if not args.execute:
                results.append(
                    {
                        "event_id": row["event_id"],
                        "lead_id": row["lead_id"],
                        "to": row["email"],
                        "subject": row["subject"],
                        "status": "preview",
                    }
                )
                continue

            ok, ref = send_via_gog(row["email"], row["subject"], row["body"])
            status = "sent" if ok else "failed"
            conn.execute(
                """
                UPDATE outreach_events
                SET status=?, provider_ref=?, error=?, actor='send_outreach.py'
                WHERE id=?
                """,
                (status, ref if ok else None, None if ok else ref, row["event_id"]),
            )
            if ok:
                conn.execute(
                    "UPDATE leads SET status='contacted', updated_at=datetime('now') WHERE id=?",
                    (row["lead_id"],),
                )
            results.append(
                {
                    "event_id": row["event_id"],
                    "lead_id": row["lead_id"],
                    "to": row["email"],
                    "status": status,
                    "provider_ref": ref if ok else None,
                    "error": None if ok else ref,
                }
            )
        conn.commit()

    result = {"ok": True, "execute": args.execute, "count": len(results), "results": results}
    log_run("send_outreach", {"execute": args.execute, "limit": args.limit}, result, "ok")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
