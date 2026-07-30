# Northline OpenClaw Lead Ops

Local-first prospecting stack built for **Northline Home Services** (late 2025): discover public local-business listings, store them in an open-source SQL CRM, score leads with deterministic CPU rules, and run gated cold outreach through Google Workspace.

Designed to run under **OpenClaw** with **`.lobster` workflows** so the agent invokes one pipeline instead of re-planning every scrape/enrich/send step (lower token burn on local models).

> Maintainer: [Muhammad Muazzain](https://github.com/MuhammadMuazzain)

---

## Two ways to drive it

| Interface | For whom |
|---|---|
| **Operator dashboard** (`streamlit run dashboard.py`) | Ops/owners — click through discover → score → approve → send |
| **Lobster workflows + JSON CLIs** | OpenClaw agent + scheduled automation |

Both hit the same CRM and the same scoring rules, so the dashboard is a window onto whatever the agent did overnight.

---

## What this system does

1. **Discover** — pull candidate businesses from **OpenStreetMap** (public Overpass API, no API key) with offline sample fallback.
2. **Normalize & upsert** — write into SQLite/Postgres CRM (`leads`, `outreach_events`, `suppressions`).
3. **Score (CPU)** — rule-based scoring (no LLM): website presence, phone/email completeness, category fit, metro priority.
4. **Draft outreach** — template + optional light rewrite; never auto-send.
5. **Approve & send** — Lobster `approval` gate, then Gmail via `gog` (or dry-run JSON).
6. **Qualify from replies** — ingest inbound email, classify interest/meeting/decline/unsubscribe with deterministic rules, update CRM.

Sheets sync is optional (`gog sheets`) for ops that live in Google Workspace day-to-day.

---

## Repo layout

```text
dashboard.py        # Streamlit operator dashboard (non-technical view)
workflows/          # .lobster pipelines (OpenClaw Lobster tool)
scripts/            # small JSON-speaking CLIs (deterministic)
sql/                # CRM schema + useful queries
openclaw/           # agent notes, tool allowlists, security boundaries
docs/               # architecture + handover
data/samples/       # public-style sample listings (offline demo)
config/             # example env + scoring weights
```

---

## Stack

| Layer | Choice |
|---|---|
| Orchestration | OpenClaw + Lobster (`.lobster` files) |
| CRM | SQLite by default (Postgres-compatible schema) |
| Workspace | Google Workspace via `gog` (Gmail / Sheets) |
| AI usage | Optional, gated; scoring/dedupe/suppression are **CPU-only** |
| Language | Python 3.10+ for CLIs |

---

## Quick start — dashboard (recommended)

No API keys needed; the demo runs entirely offline on sample listings.

```bash
git clone https://github.com/MuhammadMuazzain/northline-openclaw-leadops.git
cd northline-openclaw-leadops

python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp config/env.example .env
streamlit run dashboard.py
```

Then in the browser (`http://localhost:8501`):

1. **Create CRM tables** in the sidebar (first run only).
2. Leave **Data source** on *OpenStreetMap (fallback to sample)* — **no API key**.
3. Pick a metro/category, click **Find businesses**.
4. Click **Score leads** — deterministic rules, no AI spend.
5. Click **Prepare drafts**, review them under **Outreach**.
6. **Preview send list**, tick the approval box, then send (needs Google Workspace `gog` sign-in; otherwise stay in preview).

Tabs: **Run pipeline**, **Leads** (filter + CSV export), **Outreach** (approval queue + history), **Insights** (status/website/metro charts).

### Data sources

| Source | API key? | Notes |
|---|---|---|
| **OpenStreetMap / Overpass** | **No** | Live public map data (ODbL). Default. |
| Offline sample JSONL | No | Used if OSM is down or returns nothing |
| Website HTTP check | No | Optional toggle; not an API product |

```bash
# Live OSM (no key)
python scripts/fetch_public_listings.py --metro "Austin, TX" --category "plumbing" --limit 20 --source osm

# Offline only
python scripts/fetch_public_listings.py --metro "Austin, TX" --source sample
```

## Quick start — CLI / automation

```bash
python scripts/crm_init.py
python scripts/fetch_public_listings.py --metro "Austin, TX" --category "plumbing" --limit 25 --source auto
python scripts/score_leads.py --min-score 55
python scripts/draft_outreach.py --limit 10
python scripts/send_outreach.py --limit 5          # preview; add --execute to send
```

With Lobster CLI installed ([openclaw/lobster](https://github.com/openclaw/lobster)):

```bash
lobster run workflows/discover-public-leads.lobster --args-json "{\"metro\":\"Austin, TX\",\"category\":\"hvac\",\"limit\":25}"
lobster run workflows/score-and-queue.lobster
lobster run workflows/outreach-qualify.lobster --args-json "{\"limit\":5,\"dry_run\":true}"
```

---

## OpenClaw integration

1. Enable Lobster on the agent (`tools.alsoAllow: ["lobster"]`).
2. Point workflows at this repo (gateway cwd or absolute path inside the workspace).
3. Keep CRM credentials and Gmail OAuth **outside** agent chat context — scripts read `.env` / `gog` auth only.
4. See `openclaw/AGENT.md` for tool boundaries and prompt notes optimized for Haiku/Sonnet.

---

## Security model (summary)

External (unmonitored) conversations never receive CRM dumps. The agent may talk to leads/vendors only through **redacted tool outputs** and **approval-gated send**. Full policy: [`SECURITY.md`](./SECURITY.md).

---

## Docs

- [`docs/architecture.md`](./docs/architecture.md) — pipeline diagram and data flow
- [`docs/handover.md`](./docs/handover.md) — ops runbook for Northline
- [`SECURITY.md`](./SECURITY.md) — sensitive records + external parties

---

## License

Private delivery for Northline Home Services; shared here as a portfolio reference with sample data only.
