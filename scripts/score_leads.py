#!/usr/bin/env python3
"""
Deterministic CPU lead scoring — replaces an earlier LLM classification step.

Why: website_status / category / metro / contact completeness are structured
signals. Running them as weighted rules is faster, cheaper, and stable across
local Haiku/Sonnet budgets inside OpenClaw + Lobster.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import connect, emit, load_weights, log_run  # noqa: E402


def score_row(row, weights: dict) -> tuple[int, dict]:
    breakdown = {}
    cat = (row["category"] or "").lower()
    cat_pts = weights["category_fit"].get(cat, weights["category_fit"]["default"])
    breakdown["category_fit"] = cat_pts

    metro = row["metro"] or ""
    metro_pts = weights["metro_priority"].get(metro, weights["metro_priority"]["default"])
    breakdown["metro_priority"] = metro_pts

    ws = row["website_status"] or "unknown"
    ws_pts = weights["website_status"].get(ws, 0)
    breakdown["website_status"] = ws_pts

    contact = 0
    if row["phone"]:
        contact += weights["contact_bonus"]["has_phone"]
    if row["email"]:
        contact += weights["contact_bonus"]["has_email"]
    breakdown["contact"] = contact

    total = max(0, min(100, cat_pts + metro_pts + ws_pts + contact))
    breakdown["total"] = total
    return total, breakdown


def main() -> int:
    parser = argparse.ArgumentParser(description="CPU score leads in CRM")
    parser.add_argument("--min-score", type=int, default=None)
    parser.add_argument("--mark-qualified", action="store_true", default=True)
    args = parser.parse_args()

    weights = load_weights()
    min_score = args.min_score if args.min_score is not None else int(weights.get("min_queue_score", 55))

    updated = []
    with connect() as conn:
        rows = conn.execute("SELECT * FROM leads WHERE status NOT IN ('won','lost','suppressed')").fetchall()
        for row in rows:
            total, breakdown = score_row(row, weights)
            new_status = row["status"]
            if total >= min_score and row["status"] in ("new", "qualified"):
                new_status = "qualified"
            conn.execute(
                """
                UPDATE leads
                SET score=?, score_breakdown=?, status=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (total, json.dumps(breakdown), new_status, row["id"]),
            )
            updated.append(
                {
                    "id": row["id"],
                    "business_name": row["business_name"],
                    "score": total,
                    "status": new_status,
                    "website_status": row["website_status"],
                    "breakdown": breakdown,
                }
            )
        conn.commit()

    updated.sort(key=lambda x: x["score"], reverse=True)
    result = {"ok": True, "scored": len(updated), "min_score": min_score, "leads": updated}
    log_run("score_leads", {"min_score": min_score}, result, "ok")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
