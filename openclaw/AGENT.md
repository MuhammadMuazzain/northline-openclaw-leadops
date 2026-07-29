# OpenClaw agent notes — Northline Lead Ops

## Purpose

Ops agent that runs Lobster workflows for public-data prospecting into the Northline SQL CRM and gated Gmail outreach. Optimized for **Haiku/Sonnet** (short tool loops, JSON CLIs, almost no free-form planning).

## Enable

```json
{
  "agents": {
    "list": [
      {
        "id": "northline-lead-ops",
        "tools": {
          "alsoAllow": ["lobster"]
        }
      }
    ]
  }
}
```

## Preferred invocations (copy for prompts)

- Discover: run `workflows/discover-public-leads.lobster` with metro/category/limit.
- Score/queue: run `workflows/score-and-queue.lobster`.
- Outreach: run `workflows/outreach-qualify.lobster` (halts on approval).

Do **not** re-implement scoring in the model. Call `score_leads.py` / the Lobster workflow.

## Token hygiene

- Prefer one Lobster call over many ad-hoc shell steps.
- Ask for aggregates (`scored`, `count`) before raw lead lists.
- For any external chat agent, pipe tool JSON through `scripts/redact_for_chat.py`.

## Workspace

- Gmail send requires local `gog` auth (never paste OAuth into chat).
- Sheets sync is optional; set `GOG_SHEET_ID` when ready.

## Security

See `SECURITY.md`. External sessions must not receive CRM tools.
