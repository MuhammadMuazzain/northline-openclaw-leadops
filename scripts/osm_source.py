#!/usr/bin/env python3
"""
OpenStreetMap public-data adapter (Overpass API).

No API key required. Uses the public Overpass endpoint and optional Nominatim
geocoding for unknown metros. Falls back to callers if the network fails.

Data license: Open Database License (ODbL) — https://www.openstreetmap.org/copyright
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

USER_AGENT = "NorthlineLeadOps/1.0 (portfolio demo; contact: github.com/MuhammadMuazzain/northline-openclaw-leadops)"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Public Overpass mirrors, tried in order. The main endpoint frequently returns
# 429/504 under load, so a single failure must not fall back to sample data.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
RETRY_STATUS = {429, 502, 503, 504}

# south, west, north, east
METRO_BBOX: dict[str, tuple[float, float, float, float]] = {
    "Austin, TX": (30.10, -98.05, 30.55, -97.50),
    "Dallas, TX": (32.60, -97.10, 33.05, -96.55),
    "Houston, TX": (29.55, -95.70, 30.05, -95.10),
}

# category → list of (key, value) OSM tags
CATEGORY_TAGS: dict[str, list[tuple[str, str]]] = {
    "hvac": [
        ("craft", "hvac"),
        ("shop", "air_conditioning"),
        ("craft", "heating_engineer"),
    ],
    "plumbing": [
        ("craft", "plumber"),
        ("shop", "plumbing"),
    ],
    "roofing": [
        ("craft", "roofer"),
    ],
    "electrical": [
        ("craft", "electrician"),
        ("shop", "electrical"),
    ],
    "landscaping": [
        ("craft", "gardener"),
        ("craft", "landscaper"),
        ("shop", "garden_centre"),
    ],
}

DEFAULT_TAGS: list[tuple[str, str]] = [
    ("craft", "plumber"),
    ("craft", "electrician"),
    ("craft", "hvac"),
    ("shop", "air_conditioning"),
]


def known_metros() -> list[str]:
    return sorted(METRO_BBOX.keys())


def known_categories() -> list[str]:
    return sorted(CATEGORY_TAGS.keys())


def resolve_bbox(metro: str) -> tuple[float, float, float, float]:
    if metro in METRO_BBOX:
        return METRO_BBOX[metro]
    # fuzzy key match
    lower = metro.lower().strip()
    for key, bbox in METRO_BBOX.items():
        if lower in key.lower() or key.lower() in lower:
            return bbox
    if requests is None:
        raise RuntimeError("requests package required for live OSM fetch")
    # Nominatim (1 req/sec policy — single lookup)
    params = {"q": metro, "format": "json", "limit": 1}
    r = requests.get(
        NOMINATIM_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"Could not geocode metro: {metro}")
    bb = data[0]["boundingbox"]  # south, north, west, east as strings
    south, north, west, east = map(float, bb)
    time.sleep(1.1)  # be polite to Nominatim
    return south, west, north, east


def _overpass_query(bbox: tuple[float, float, float, float], tags: list[tuple[str, str]], limit: int) -> str:
    south, west, north, east = bbox
    parts = []
    for key, value in tags:
        parts.append(f'  node["{key}"="{value}"]({south},{west},{north},{east});')
        parts.append(f'  way["{key}"="{value}"]({south},{west},{north},{east});')
    body = "\n".join(parts)
    # overpass out count can still be large; we slice in Python
    return f"""
[out:json][timeout:60];
(
{body}
);
out center tags {max(limit * 3, 30)};
""".strip()


def _element_to_row(el: dict[str, Any], metro: str, category: str) -> dict[str, Any] | None:
    tags = el.get("tags") or {}
    name = tags.get("name")
    if not name:
        return None
    website = tags.get("website") or tags.get("contact:website") or tags.get("url") or ""
    phone = tags.get("phone") or tags.get("contact:phone") or tags.get("telephone") or ""
    email = tags.get("email") or tags.get("contact:email") or ""
    city = tags.get("addr:city") or ""
    state = tags.get("addr:state") or ""
    osm_type = el.get("type", "node")
    osm_id = el.get("id")
    source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_id else ""
    return {
        "name": name,
        "business_name": name,
        "category": category or tags.get("craft") or tags.get("shop") or "local_service",
        "metro": metro,
        "city": city or metro.split(",")[0].strip(),
        "state": state or (metro.split(",")[-1].strip() if "," in metro else ""),
        "phone": phone,
        "email": email,
        "website_url": website,
        "source": "openstreetmap",
        "source_url": source_url,
        "osm_id": f"{osm_type}/{osm_id}",
    }


def _post_overpass(query: str, endpoints: list[str], attempts_per_endpoint: int = 2) -> dict[str, Any]:
    """
    POST an Overpass query, walking mirrors and retrying transient failures.
    Raises the last error only after every endpoint has been tried.
    """
    last_error: Exception | None = None
    for endpoint in endpoints:
        for attempt in range(attempts_per_endpoint):
            try:
                r = requests.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=90,
                )
                if r.status_code in RETRY_STATUS:
                    last_error = RuntimeError(f"{r.status_code} from {endpoint}")
                    if attempt + 1 < attempts_per_endpoint:
                        time.sleep(2 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as e:  # network error, bad JSON, non-retry HTTP
                last_error = e
                if attempt + 1 < attempts_per_endpoint:
                    time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"all Overpass endpoints failed; last error: {last_error}")


def fetch_osm_listings(
    metro: str,
    category: str | None = None,
    limit: int = 25,
    overpass_url: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch business-like POIs from OpenStreetMap for a metro/category.
    Raises on hard failures so callers can fall back to sample data.
    """
    if requests is None:
        raise RuntimeError("requests package required for live OSM fetch")
    if not metro:
        metro = "Austin, TX"

    bbox = resolve_bbox(metro)
    cat = (category or "").lower().strip()
    tags = CATEGORY_TAGS.get(cat, DEFAULT_TAGS)
    if cat and cat not in CATEGORY_TAGS:
        # unknown category label still stored on rows; query default trade tags
        tags = DEFAULT_TAGS

    endpoints = [overpass_url] if overpass_url else list(OVERPASS_MIRRORS)
    query = _overpass_query(bbox, tags, limit)
    payload = _post_overpass(query, endpoints)
    elements = payload.get("elements") or []

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for el in elements:
        row = _element_to_row(el, metro=metro, category=cat or "local_service")
        if not row:
            continue
        key = row["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows
