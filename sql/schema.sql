-- Northline CRM schema (SQLite default; Postgres-compatible types noted)
-- Designed for OpenClaw agents via thin Python CLIs (no ORM required).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS leads (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  external_key      TEXT NOT NULL UNIQUE,          -- hash of name|city|phone
  business_name     TEXT NOT NULL,
  category          TEXT,
  metro             TEXT,
  city              TEXT,
  state             TEXT,
  phone             TEXT,
  email             TEXT,
  website_url       TEXT,
  website_status    TEXT NOT NULL DEFAULT 'unknown', -- none|active|parked|social_only|unknown
  source            TEXT NOT NULL DEFAULT 'public_listing',
  source_url        TEXT,
  score             INTEGER NOT NULL DEFAULT 0,
  score_breakdown   TEXT,                          -- JSON
  status            TEXT NOT NULL DEFAULT 'new',    -- new|qualified|queued|contacted|replied|won|lost|suppressed
  owner             TEXT,
  notes             TEXT,
  raw_json          TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS outreach_events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id       INTEGER NOT NULL REFERENCES leads(id),
  channel       TEXT NOT NULL DEFAULT 'email',      -- email|manual
  direction     TEXT NOT NULL DEFAULT 'outbound',
  template_id   TEXT,
  subject       TEXT,
  body          TEXT,
  status        TEXT NOT NULL,                      -- drafted|approved|sent|failed|skipped|replied
  provider_ref  TEXT,
  error         TEXT,
  actor         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS suppressions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  email       TEXT UNIQUE,
  phone       TEXT,
  reason      TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  workflow    TEXT NOT NULL,
  args_json   TEXT,
  result_json TEXT,
  status      TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_leads_status_score ON leads(status, score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_metro_category ON leads(metro, category);
CREATE INDEX IF NOT EXISTS idx_outreach_lead ON outreach_events(lead_id, created_at);
