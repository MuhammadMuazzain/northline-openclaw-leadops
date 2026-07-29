# Handover — Northline Home Services

## Daily ops

1. Run discover for target metros/categories.
2. Run score-and-queue.
3. Review drafted outreach in SQL (`outreach_events` status=`drafted`) or CSV from `sheets_sync.py --csv-only`.
4. Run outreach-qualify; approve only after spot-checking recipients.

## Adding a metro

- Drop public listing rows into `data/samples/` or wire a new adapter that emits the same JSON keys.
- Optionally bump `config/scoring_weights.json` → `metro_priority`.

## Suppression

```sql
INSERT INTO suppressions (email, reason) VALUES ('someone@example.com', 'requested_unsubscribe');
```

## Postgres

Schema is SQLite-first. For Postgres, swap `INTEGER PRIMARY KEY AUTOINCREMENT` for `SERIAL PRIMARY KEY` and `datetime('now')` for `NOW()`, then point a thin `psycopg` wrapper at the same queries (not shipped in this handoff; SQLite covered Northline's volume).
