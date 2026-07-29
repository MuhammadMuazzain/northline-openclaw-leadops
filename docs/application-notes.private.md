# Application answer bank (internal)
# Map portfolio pieces to common OpenClaw hiring questions — do not paste this file publicly.

## Security (sensitive CRM + unmonitored external chats)
Point to SECURITY.md + openclaw/AGENT.md session split + redact_for_chat.py + Lobster send approval.

## Lobster automation finding leads from public data
workflows/discover-public-leads.lobster + scripts/fetch_public_listings.py (public listing ingest, website_status heuristics).

## SQL CRM integrated with OpenClaw scraping
sql/schema.sql (leads, outreach_events, suppressions, agent_runs) + CRM CLIs + AGENT.md Lobster enablement.

## Automated outreach sequence to qualify cold leads
workflows/outreach-qualify.lobster + draft_outreach.py + send_outreach.py (preview -> approval -> gog send) + suppression list.

## Replaced AI inference with deterministic CPU process
scripts/score_leads.py + config/scoring_weights.json (documented in docs/architecture.md as replacing LLM website/fit classification).
