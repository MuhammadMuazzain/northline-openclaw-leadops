#!/usr/bin/env python3
"""
Send or dry-run outreach for drafted events.

Real send path shells out to `gog gmail send` when --execute is passed.
Default is dry-run JSON so Lobster approval can gate the execute step.

Demo mode (--simulate) marks drafts as sent without calling Gmail, for
walkthroughs when OAuth is unavailable.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import connect, emit, log_run  # noqa: E402


def gog_account() -> str:
    return (os.getenv("OUTREACH_GMAIL_ACCOUNT") or os.getenv("GOG_ACCOUNT") or "").strip()


def explain_gog_error(raw: str) -> str:
    text = (raw or "").strip()
    lower = text.lower()
    if "gog_not_installed" in lower or "not found" in lower:
        return "gog CLI not found on PATH. Install gog, then run: gog auth add you@gmail.com --services gmail"
    if "invalid_grant" in lower or "bad request" in lower:
        return (
            "Gmail OAuth token expired or revoked. Re-auth with: "
            "gog auth add maziright2345@gmail.com --services gmail "
            "(use your account email), then try again."
        )
    if "insufficient" in lower or "scope" in lower:
        return "Gmail scope missing. Re-auth with --services gmail and approve send permission."
    if not text:
        return "gog send failed with no output. Check: gog auth list"
    return text[:500]


def send_via_gog(to: str, subject: str, body: str) -> tuple[bool, str]:
    gog_bin = shutil.which("gog")
    if not gog_bin:
        return False, explain_gog_error("gog_not_installed")

    cmd = [gog_bin, "gmail", "send", "--to", to, "--subject", subject, "--body", body, "--json"]
    account = gog_account()
    if account:
        cmd.extend(["-a", account])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode == 0:
            return True, (proc.stdout or out).strip()[:500]
        return False, explain_gog_error(out or "gog_failed")
    except Exception as e:
        return False, explain_gog_error(str(e))


def process_drafts(limit: int, execute: bool = False, simulate: bool = False) -> list[dict]:
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
            (limit,),
        ).fetchall()

        for row in rows:
            if not execute and not simulate:
                results.append(
                    {
                        "event_id": row["event_id"],
                        "lead_id": row["lead_id"],
                        "business_name": row["business_name"],
                        "to": row["email"],
                        "subject": row["subject"],
                        "status": "preview",
                    }
                )
                continue

            if simulate:
                ok, ref = True, "simulated_local_send"
                status = "sent"
                actor = "simulate"
            else:
                ok, ref = send_via_gog(row["email"], row["subject"], row["body"])
                status = "sent" if ok else "failed"
                actor = "send_outreach.py"

            conn.execute(
                """
                UPDATE outreach_events
                SET status=?, provider_ref=?, error=?, actor=?
                WHERE id=?
                """,
                (
                    status,
                    ref if ok else None,
                    None if ok else ref,
                    actor,
                    row["event_id"],
                ),
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
                    "business_name": row["business_name"],
                    "to": row["email"],
                    "subject": row["subject"],
                    "status": status,
                    "provider_ref": ref if ok else None,
                    "error": None if ok else ref,
                    "detail": ref,
                }
            )
        conn.commit()
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--execute", action="store_true", help="Actually send via gog")
    parser.add_argument("--simulate", action="store_true", help="Mark as sent without Gmail (demo)")
    parser.add_argument("--stdin-json", action="store_true", help="Optional filter payload from stdin")
    args = parser.parse_args()

    if args.stdin_json:
        try:
            json.load(sys.stdin)
        except Exception:
            pass

    results = process_drafts(args.limit, execute=args.execute, simulate=args.simulate)
    result = {
        "ok": True,
        "execute": args.execute,
        "simulate": args.simulate,
        "account": gog_account() or None,
        "count": len(results),
        "results": results,
    }
    log_run(
        "send_outreach",
        {"execute": args.execute, "simulate": args.simulate, "limit": args.limit},
        result,
        "ok",
    )
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
