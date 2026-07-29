#!/usr/bin/env python3
"""Draft cold outreach for qualified leads (templates; no send)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import connect, emit, log_run  # noqa: E402

TEMPLATE_ID = "northline_v1_intro"


def render(lead, from_name: str) -> tuple[str, str]:
    biz = lead["business_name"]
    city = lead["city"] or lead["metro"] or "your area"
    subject = f"Quick idea for {biz}'s online presence"
    body = (
        f"Hi {biz} team,\n\n"
        f"I came across your listing serving {city} and noticed you may not have a full website "
        f"(or it's mostly social). Local customers often search Google before calling - a simple "
        f"site usually helps with calls and trust.\n\n"
        f"Would you be open to a short reply if that's useful? If not, say unsubscribe and I won't follow up.\n\n"
        f"- {from_name}\n"
    )
    return subject, body


def suppressed(conn, email: str | None) -> bool:
    if not email:
        return True
    row = conn.execute("SELECT 1 FROM suppressions WHERE email = ? COLLATE NOCASE", (email,)).fetchone()
    return row is not None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--min-score", type=int, default=55)
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()
    from_name = os.getenv("OUTREACH_FROM_NAME", "Northline Home Services")

    drafts = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM leads
            WHERE status IN ('qualified', 'queued')
              AND score >= ?
              AND email IS NOT NULL AND email != ''
            ORDER BY score DESC
            LIMIT ?
            """,
            (args.min_score, args.limit),
        ).fetchall()

        for lead in rows:
            if suppressed(conn, lead["email"]):
                drafts.append({"id": lead["id"], "skipped": True, "reason": "suppressed"})
                continue
            subject, body = render(lead, from_name)
            item = {
                "lead_id": lead["id"],
                "business_name": lead["business_name"],
                "email": lead["email"],
                "score": lead["score"],
                "template_id": TEMPLATE_ID,
                "subject": subject,
                "body": body,
            }
            if not args.dry_run:
                conn.execute(
                    """
                    INSERT INTO outreach_events (lead_id, template_id, subject, body, status, actor)
                    VALUES (?, ?, ?, ?, 'drafted', 'draft_outreach.py')
                    """,
                    (lead["id"], TEMPLATE_ID, subject, body),
                )
                conn.execute(
                    "UPDATE leads SET status='queued', updated_at=datetime('now') WHERE id=?",
                    (lead["id"],),
                )
            drafts.append(item)
        if not args.dry_run:
            conn.commit()

    result = {"ok": True, "dry_run": args.dry_run, "count": len(drafts), "drafts": drafts}
    log_run("draft_outreach", vars(args), {"count": len(drafts)}, "ok")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
