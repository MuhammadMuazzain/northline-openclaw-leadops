# Security model — Northline OpenClaw Lead Ops

Context: an OpenClaw agent that can **read/write a SQL CRM with sensitive prospect records**, while also participating in **unmonitored chats with external parties** (cold leads, vendors, contractors).

## Threat model (short)

| Risk | Mitigation |
|---|---|
| Agent leaks CRM rows into a lead chat | Tool allowlists + redaction layer; CRM tools blocked in external sessions |
| Accidental bulk email / spam | Lobster `approval` before every send; daily throttle; suppression list |
| Prompt injection from scraped pages / replies | Treat all inbound text as untrusted; never `exec` from lead content |
| Secrets in model context | `.env` / OS keychain only; scripts never print tokens |
| Over-privileged agent | Split agents: `lead-ops` (CRM + Lobster) vs `external-chat` (message only) |

## Boundaries

1. **Session isolation**  
   - Internal ops session (`lead-ops`): may call Lobster workflows + CRM CLIs.  
   - External party session: **no** `crm_*`, **no** raw SQL, **no** Sheets export tools.

2. **Least privilege tools**  
   OpenClaw allowlist for external sessions is messaging-only. CRM mutations happen only inside Lobster pipelines started from an internal session.

3. **Redaction by default**  
   CLI `--json` outputs for external-facing steps strip phone/email unless the step is explicitly `outreach.send` after approval. Sample redactor: `scripts/redact_for_chat.py`.

4. **Approval gates for side effects**  
   Send, suppress-list edits that unlock contacts, and Sheets writes that leave the machine require Lobster `approval:`.

5. **Suppression & compliance**  
   Hard stop if email is in `suppressions`. Outreach templates include identification + opt-out path. No SMS in this delivery (stricter consent rules).

6. **Audit**  
   Every outreach attempt writes `outreach_events` (status, template id, actor, timestamp). Failed sends do not retry automatically without a new approved run.

## What the model is allowed to see

- Aggregates: “12 HVAC leads in Austin scoring ≥ 70”
- Non-PII fields for triage: city, category, score, website_status
- Draft subject/body **after** templates are filled, still pending approval

## What the model must not see in external chats

- Full CRM dumps, SQL, connection strings
- Other leads’ contact data
- Internal scoring weights / metro priorities (optional; keep in config files)

## Operational checklist

- [ ] Separate OpenClaw agent IDs for ops vs external chat  
- [ ] Lobster enabled only on ops agent  
- [ ] `.env` not committed; `gog` auth local to the host  
- [ ] Review `outreach_events` weekly for anomalies  
