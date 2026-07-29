#!/usr/bin/env python3
"""
Fetch / ingest public listing candidates into the CRM.

Default mode reads the offline sample JSONL (safe for demos).
Optional --live-check probes website_url with HTTP HEAD/GET heuristics.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, connect, emit, external_key, log_run  # noqa: E402

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


SOCIAL_HOSTS = {"facebook.com", "fb.com", "instagram.com", "tiktok.com", "x.com", "twitter.com", "linkedin.com"}


def classify_website(url: str | None, live: bool) -> str:
    if not url or not str(url).strip():
        return "none"
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if any(host == s or host.endswith("." + s) for s in SOCIAL_HOSTS):
        return "social_only"
    if "parking" in url.lower() or "parked" in url.lower():
        return "parked"
    if not live or requests is None:
        return "unknown" if url else "none"
    try:
        r = requests.get(url, timeout=8, allow_redirects=True)
        text = (r.text or "")[:2000].lower()
        if r.status_code >= 400:
            return "none"
        if "domain is for sale" in text or "buy this domain" in text:
            return "parked"
        return "active"
    except Exception:
        return "unknown"


def load_candidates(path: Path, metro: str | None, category: str | None, limit: int) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if metro and row.get("metro", "").lower() != metro.lower():
                # also allow substring match on city listings
                if metro.lower() not in str(row.get("metro", "")).lower():
                    continue
            if category and row.get("category", "").lower() != category.lower():
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def upsert(row: dict, live: bool) -> dict:
    name = row.get("name") or row.get("business_name")
    website_url = row.get("website_url") or ""
    website_status = classify_website(website_url or None, live=live)
    key = external_key(name, row.get("city"), row.get("phone"))
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO leads (
              external_key, business_name, category, metro, city, state,
              phone, email, website_url, website_status, source, source_url, raw_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(external_key) DO UPDATE SET
              phone=excluded.phone,
              email=excluded.email,
              website_url=excluded.website_url,
              website_status=excluded.website_status,
              source_url=excluded.source_url,
              raw_json=excluded.raw_json,
              updated_at=datetime('now')
            """,
            (
                key,
                name,
                row.get("category"),
                row.get("metro"),
                row.get("city"),
                row.get("state"),
                row.get("phone"),
                row.get("email") or None,
                website_url or None,
                website_status,
                row.get("source") or "public_listing",
                row.get("source_url"),
                json.dumps(row),
            ),
        )
        conn.commit()
        lead_id = conn.execute("SELECT id FROM leads WHERE external_key=?", (key,)).fetchone()["id"]
    return {
        "id": lead_id,
        "external_key": key,
        "business_name": name,
        "website_status": website_status,
        "metro": row.get("metro"),
        "category": row.get("category"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest public listings into Northline CRM")
    parser.add_argument("--metro", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--sample", default=os.getenv("NORTHLINE_SAMPLE_PATH", "data/samples/public_listings.jsonl"))
    parser.add_argument("--live-check", action="store_true", default=os.getenv("NORTHLINE_LIVE_WEBSITE_CHECK") == "1")
    args = parser.parse_args()

    sample = Path(args.sample)
    if not sample.is_absolute():
        sample = ROOT / sample

    candidates = load_candidates(sample, args.metro or None, args.category or None, args.limit)
    upserted = [upsert(c, live=args.live_check) for c in candidates]
    result = {
        "ok": True,
        "ingested": len(upserted),
        "metro": args.metro or None,
        "category": args.category or None,
        "leads": upserted,
    }
    log_run("fetch_public_listings", vars(args), result, "ok")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
