#!/usr/bin/env python3
"""
Qualify cold leads from inbound email replies.

1) Pull recent inbox messages via gog (or load a demo JSONL)
2) Match From: address to contacted CRM leads
3) Classify reply with deterministic rules (no LLM)
4) Update lead status / suppressions / reply_events

This is the post-send qualification loop the outreach question asks for.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from email.utils import parseaddr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_reply import classify_reply  # noqa: E402
from common import ROOT, connect, emit, log_run  # noqa: E402


def gog_account() -> str:
    return (os.getenv("OUTREACH_GMAIL_ACCOUNT") or os.getenv("GOG_ACCOUNT") or "").strip()


def gog_client() -> str:
    return (os.getenv("GOG_CLIENT") or os.getenv("OUTREACH_GOG_CLIENT") or "personal").strip()


def ensure_reply_schema() -> None:
    sql = (ROOT / "sql" / "schema_replies.sql").read_text(encoding="utf-8")
    with connect() as conn:
        conn.executescript(sql)
        # additive columns on leads (ignore if already present)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
        if "qualification" not in cols:
            conn.execute("ALTER TABLE leads ADD COLUMN qualification TEXT")
        if "qualification_reason" not in cols:
            conn.execute("ALTER TABLE leads ADD COLUMN qualification_reason TEXT")
        if "last_reply_at" not in cols:
            conn.execute("ALTER TABLE leads ADD COLUMN last_reply_at TEXT")
        conn.commit()


def _gog_cmd(args: list[str]) -> list[str]:
    gog_bin = shutil.which("gog")
    if not gog_bin:
        raise RuntimeError("gog_not_installed")
    cmd = [gog_bin, *args, "--json", "--client", gog_client() or "personal"]
    account = gog_account()
    if account:
        cmd.extend(["-a", account])
    return cmd


def _run_json(cmd: list[str]) -> dict | list:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(((proc.stderr or out) or "gog_failed")[:500])
    return json.loads(out) if out else {}


def fetch_gmail_candidates(query: str, max_results: int) -> list[dict]:
    """Search Gmail threads/messages and hydrate bodies."""
    cmd = _gog_cmd(["gmail", "search", query, "--max", str(max_results)])
    payload = _run_json(cmd)
    # gog shapes vary: list, or {threads:[]}, or {messages:[]}
    items = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("threads") or payload.get("messages") or payload.get("results") or []
        if not items and payload.get("id"):
            items = [payload]

    messages: list[dict] = []
    for item in items:
        msg_id = item.get("id") or item.get("messageId") or item.get("message_id")
        # thread search often returns thread id + messages
        if not msg_id and item.get("messages"):
            msg_id = item["messages"][-1].get("id")
        if not msg_id:
            continue
        detail = _run_json(_gog_cmd(["gmail", "get", str(msg_id), "--format", "full"]))
        messages.append(_normalize_gmail_message(detail if isinstance(detail, dict) else item))
    return [m for m in messages if m.get("from_email")]


def _header_map(detail: dict) -> dict[str, str]:
    headers = {}
    payload = detail.get("payload") or detail
    for h in payload.get("headers") or detail.get("headers") or []:
        name = (h.get("name") or "").lower()
        headers[name] = h.get("value") or ""
    # flattened forms some CLIs return
    for key in ("from", "subject", "to"):
        if key in detail and key not in headers:
            headers[key] = str(detail.get(key) or "")
    return headers


def _extract_body(detail: dict) -> str:
    if detail.get("body"):
        return str(detail["body"])
    if detail.get("snippet"):
        return str(detail["snippet"])
    payload = detail.get("payload") or {}
    parts = payload.get("parts") or []
    texts = []
    if payload.get("body", {}).get("data"):
        import base64

        try:
            texts.append(base64.urlsafe_b64decode(payload["body"]["data"] + "==").decode("utf-8", "ignore"))
        except Exception:
            pass
    for part in parts:
        mime = (part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data")
        if data and ("text/plain" in mime or mime == ""):
            import base64

            try:
                texts.append(base64.urlsafe_b64decode(data + "==").decode("utf-8", "ignore"))
            except Exception:
                continue
    return "\n".join(texts).strip() or str(detail.get("snippet") or "")


def _normalize_gmail_message(detail: dict) -> dict:
    headers = _header_map(detail)
    from_raw = headers.get("from") or detail.get("from") or ""
    _, from_email = parseaddr(from_raw)
    from_email = (from_email or from_raw).strip().lower()
    return {
        "gmail_message_id": str(detail.get("id") or detail.get("messageId") or ""),
        "gmail_thread_id": str(detail.get("threadId") or detail.get("thread_id") or ""),
        "from_email": from_email,
        "subject": headers.get("subject") or detail.get("subject") or "",
        "body_text": _extract_body(detail),
        "raw": detail,
    }


def load_demo_replies(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row["from_email"] = (row.get("from_email") or "").strip().lower()
            rows.append(row)
    return rows


def match_lead(conn, from_email: str) -> dict | None:
    if not from_email:
        return None
    row = conn.execute(
        """
        SELECT * FROM leads
        WHERE lower(email) = lower(?)
          AND status IN ('contacted','queued','replied','qualified','won')
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (from_email,),
    ).fetchone()
    return dict(row) if row else None


def latest_outbound(conn, lead_id: int) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM outreach_events
        WHERE lead_id = ? AND direction = 'outbound' AND status IN ('sent','drafted','replied')
        ORDER BY created_at DESC LIMIT 1
        """,
        (lead_id,),
    ).fetchone()
    return int(row["id"]) if row else None


def apply_qualification(conn, lead: dict, msg: dict) -> dict:
    classification = classify_reply(msg.get("subject"), msg.get("body_text"))
    gmail_id = msg.get("gmail_message_id") or f"demo-{lead['id']}-{abs(hash(msg.get('body_text') or '')) % 10_000_000}"

    existing = conn.execute(
        "SELECT id FROM reply_events WHERE gmail_message_id = ?",
        (gmail_id,),
    ).fetchone()
    if existing:
        return {
            "lead_id": lead["id"],
            "business_name": lead["business_name"],
            "skipped": True,
            "reason": "already_processed",
            "classification": classification.label,
        }

    outreach_id = latest_outbound(conn, lead["id"])
    conn.execute(
        """
        INSERT INTO reply_events (
          lead_id, outreach_event_id, gmail_message_id, gmail_thread_id,
          from_email, subject, body_text, classification, classification_rule,
          confidence, lead_status_after, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead["id"],
            outreach_id,
            gmail_id,
            msg.get("gmail_thread_id"),
            msg.get("from_email"),
            msg.get("subject"),
            msg.get("body_text"),
            classification.label,
            classification.rule,
            classification.confidence,
            classification.lead_status,
            json.dumps(msg.get("raw") or msg),
        ),
    )

    conn.execute(
        """
        UPDATE leads
        SET status = ?,
            qualification = ?,
            qualification_reason = ?,
            last_reply_at = datetime('now'),
            notes = COALESCE(notes,'') || ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            classification.lead_status,
            classification.label,
            classification.rule,
            f"\n[reply:{classification.label}] {(msg.get('body_text') or '')[:180]}",
            lead["id"],
        ),
    )

    if outreach_id:
        conn.execute(
            "UPDATE outreach_events SET status='replied' WHERE id=? AND status='sent'",
            (outreach_id,),
        )

    if classification.label == "unsubscribe" and lead.get("email"):
        conn.execute(
            """
            INSERT INTO suppressions (email, reason)
            VALUES (?, 'reply_unsubscribe')
            ON CONFLICT(email) DO UPDATE SET reason=excluded.reason
            """,
            (lead["email"],),
        )

    return {
        "lead_id": lead["id"],
        "business_name": lead["business_name"],
        "from_email": msg.get("from_email"),
        "classification": classification.label,
        "rule": classification.rule,
        "confidence": classification.confidence,
        "lead_status": classification.lead_status,
        "subject": msg.get("subject"),
        "skipped": False,
    }


def process_messages(messages: list[dict]) -> list[dict]:
    ensure_reply_schema()
    results = []
    with connect() as conn:
        for msg in messages:
            lead = match_lead(conn, msg.get("from_email") or "")
            if not lead:
                results.append(
                    {
                        "from_email": msg.get("from_email"),
                        "skipped": True,
                        "reason": "no_matching_contacted_lead",
                        "subject": msg.get("subject"),
                    }
                )
                continue
            results.append(apply_qualification(conn, lead, msg))
        conn.commit()
    return results


def seed_contacted_for_demo(demo_path: Path) -> None:
    """Ensure demo from_emails exist as contacted leads so classification can apply."""
    ensure_reply_schema()
    replies = load_demo_replies(demo_path)
    with connect() as conn:
        for i, msg in enumerate(replies, start=1):
            email = msg.get("from_email")
            if not email:
                continue
            existing = conn.execute("SELECT id FROM leads WHERE lower(email)=lower(?)", (email,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE leads SET status='contacted', updated_at=datetime('now') WHERE id=?",
                    (existing["id"],),
                )
                lead_id = existing["id"]
            else:
                cur = conn.execute(
                    """
                    INSERT INTO leads (
                      external_key, business_name, category, metro, city, state,
                      email, website_status, source, status, score
                    ) VALUES (?, ?, 'plumbing', 'Austin, TX', 'Austin', 'TX', ?, 'none', 'demo_reply', 'contacted', 80)
                    """,
                    (f"demo-reply-{i}-{email}", msg.get("business_name") or f"Demo Lead {i}", email),
                )
                lead_id = cur.lastrowid
            # ensure an outbound sent event exists
            has = conn.execute(
                "SELECT 1 FROM outreach_events WHERE lead_id=? AND status='sent' LIMIT 1",
                (lead_id,),
            ).fetchone()
            if not has:
                conn.execute(
                    """
                    INSERT INTO outreach_events (lead_id, template_id, subject, body, status, actor, direction)
                    VALUES (?, 'northline_v1_intro', 'Quick idea for your online presence', 'demo outbound', 'sent', 'demo_seed', 'outbound')
                    """,
                    (lead_id,),
                )
        conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify CRM leads from email replies")
    parser.add_argument("--source", choices=["gmail", "demo"], default="demo")
    parser.add_argument("--query", default="in:inbox newer_than:14d -in:chats")
    parser.add_argument("--max", type=int, default=15)
    parser.add_argument(
        "--demo-file",
        default=str(ROOT / "data" / "samples" / "inbound_replies.jsonl"),
    )
    parser.add_argument("--seed-demo-leads", action="store_true", help="Create contacted leads for demo reply emails")
    args = parser.parse_args()

    ensure_reply_schema()
    warning = None

    if args.source == "demo":
        demo_path = Path(args.demo_file)
        if not demo_path.is_absolute():
            demo_path = ROOT / demo_path
        if args.seed_demo_leads:
            seed_contacted_for_demo(demo_path)
        messages = load_demo_replies(demo_path)
        source_used = "demo"
    else:
        try:
            messages = fetch_gmail_candidates(args.query, args.max)
            source_used = "gmail"
        except Exception as e:
            warning = f"Gmail fetch failed ({e}); falling back to demo replies."
            demo_path = Path(args.demo_file)
            if not demo_path.is_absolute():
                demo_path = ROOT / demo_path
            seed_contacted_for_demo(demo_path)
            messages = load_demo_replies(demo_path)
            source_used = "demo"

    results = process_messages(messages)
    applied = [r for r in results if not r.get("skipped")]
    summary = {
        "interested": sum(1 for r in applied if r.get("classification") == "interested"),
        "meeting": sum(1 for r in applied if r.get("classification") == "meeting"),
        "question": sum(1 for r in applied if r.get("classification") == "question"),
        "not_interested": sum(1 for r in applied if r.get("classification") == "not_interested"),
        "unsubscribe": sum(1 for r in applied if r.get("classification") == "unsubscribe"),
        "ooo": sum(1 for r in applied if r.get("classification") == "ooo"),
        "unclear": sum(1 for r in applied if r.get("classification") == "unclear"),
    }
    payload = {
        "ok": True,
        "source_used": source_used,
        "warning": warning,
        "scanned": len(messages),
        "applied": len(applied),
        "summary": summary,
        "results": results,
    }
    log_run("qualify_replies", vars(args), {"applied": len(applied), "summary": summary}, "ok")
    emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
