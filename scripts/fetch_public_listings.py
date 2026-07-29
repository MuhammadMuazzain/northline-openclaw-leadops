#!/usr/bin/env python3
"""
Fetch / ingest public listing candidates into the CRM.

Sources:
  - osm    : live OpenStreetMap via Overpass (no API key)
  - sample : offline JSONL demo file
  - auto   : try OSM first, fall back to sample on failure/empty

Optional --live-check probes website_url with HTTP heuristics.
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
from osm_source import fetch_osm_listings, known_categories, known_metros  # noqa: E402

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
                if metro.lower() not in str(row.get("metro", "")).lower():
                    continue
            if category and row.get("category", "").lower() != category.lower():
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def sample_path(explicit: str | None = None) -> Path:
    raw = explicit or os.getenv("NORTHLINE_SAMPLE_PATH", "data/samples/public_listings.jsonl")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def collect_candidates(
    metro: str | None,
    category: str | None,
    limit: int,
    source: str = "auto",
    sample_file: str | None = None,
) -> tuple[list[dict], str, str | None]:
    """
    Returns (rows, source_used, warning).
    source_used is 'openstreetmap' or 'sample'.
    """
    source = (source or "auto").lower().strip()
    warning = None
    path = sample_path(sample_file)

    if source in ("osm", "auto", "openstreetmap"):
        try:
            rows = fetch_osm_listings(
                metro=metro or "Austin, TX",
                category=category or None,
                limit=limit,
            )
            if rows:
                return rows, "openstreetmap", None
            warning = "OpenStreetMap returned 0 matches; using sample file."
        except Exception as e:
            warning = f"OpenStreetMap fetch failed ({e}); using sample file."
            if source in ("osm", "openstreetmap"):
                # still fall back so demos never hard-fail unless sample missing
                pass

    if source == "sample" or source == "auto" or warning:
        rows = load_candidates(path, metro or None, category or None, limit)
        if not rows and metro:
            # last resort: ignore metro filter on sample
            rows = load_candidates(path, None, category or None, limit)
            if rows and warning:
                warning += " Sample metro filter also relaxed."
        return rows, "sample", warning

    return [], "sample", warning or "No candidates found."


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
              source=excluded.source,
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
        "source": row.get("source") or "public_listing",
        "phone": row.get("phone") or "",
        "email": row.get("email") or "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest public listings into Northline CRM")
    parser.add_argument("--metro", default="Austin, TX")
    parser.add_argument("--category", default="")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument(
        "--source",
        default=os.getenv("NORTHLINE_DATA_SOURCE", "auto"),
        choices=["auto", "osm", "sample"],
        help="auto=OSM then sample fallback (default)",
    )
    parser.add_argument("--sample", default=os.getenv("NORTHLINE_SAMPLE_PATH", "data/samples/public_listings.jsonl"))
    parser.add_argument("--live-check", action="store_true", default=os.getenv("NORTHLINE_LIVE_WEBSITE_CHECK") == "1")
    args = parser.parse_args()

    candidates, used, warning = collect_candidates(
        metro=args.metro or None,
        category=args.category or None,
        limit=args.limit,
        source=args.source,
        sample_file=args.sample,
    )
    upserted = [upsert(c, live=args.live_check) for c in candidates]
    result = {
        "ok": True,
        "ingested": len(upserted),
        "source_used": used,
        "warning": warning,
        "metro": args.metro or None,
        "category": args.category or None,
        "available_metros": known_metros(),
        "available_categories": known_categories(),
        "leads": upserted,
        "api_key_required": False,
    }
    log_run("fetch_public_listings", vars(args), {"ingested": len(upserted), "source_used": used, "warning": warning}, "ok")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
