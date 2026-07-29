# Architecture

```text
Public listings (sample JSONL / future adapters)
        │
        ▼
 fetch_public_listings.py  ── website_status heuristics (CPU)
        │
        ▼
   SQLite/Postgres CRM (leads, outreach_events, suppressions)
        │
        ▼
 score_leads.py  ── weighted rules (CPU; replaced LLM classifier)
        │
        ▼
 draft_outreach.py ── templates → outreach_events (drafted)
        │
        ▼
 Lobster approval gate
        │
        ▼
 send_outreach.py ── gog gmail send (or dry-run)
        │
        ▼
 optional sheets_sync.py ── Google Sheets queue for humans
```

## Why Lobster

Northline's OpenClaw agent used to plan scrape → upsert → score → draft as separate tool calls every morning. That burned context on local models. Lobster collapses each path into one resumable workflow with an explicit send approval.

## Deterministic replacement example

**Before:** an LLM step classified “has usable website?” from scraped HTML snippets.  
**After:** `classify_website()` + `score_leads.py` weights (`none` / `social_only` / `parked` / `active`). Same CRM fields, faster and stable — documented in `scripts/score_leads.py`.
