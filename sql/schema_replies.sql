-- Migration / additive objects for reply-based lead qualification
-- Safe to run after schema.sql (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS reply_events (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id             INTEGER REFERENCES leads(id),
  outreach_event_id   INTEGER REFERENCES outreach_events(id),
  gmail_message_id    TEXT UNIQUE,
  gmail_thread_id     TEXT,
  from_email          TEXT,
  subject             TEXT,
  body_text           TEXT,
  classification      TEXT NOT NULL,  -- interested|meeting|question|not_interested|unsubscribe|ooo|unclear
  classification_rule TEXT,           -- which rule fired
  confidence          REAL NOT NULL DEFAULT 1.0,
  lead_status_after   TEXT,
  raw_json            TEXT,
  created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reply_lead ON reply_events(lead_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reply_class ON reply_events(classification);
