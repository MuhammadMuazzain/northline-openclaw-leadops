name: score-and-queue
description: Deterministic CPU scoring then draft outreach queue (no send).
args:
  min_score:
    default: "55"
  draft_limit:
    default: "10"
steps:
  - id: score
    env:
      MIN_SCORE: "$LOBSTER_ARG_MIN_SCORE"
    run: python scripts/score_leads.py --min-score "$MIN_SCORE"

  - id: draft
    env:
      LIMIT: "$LOBSTER_ARG_DRAFT_LIMIT"
      MIN_SCORE: "$LOBSTER_ARG_MIN_SCORE"
    run: python scripts/draft_outreach.py --limit "$LIMIT" --min-score "$MIN_SCORE"
    stdin: $score.stdout

  - id: sheets_preview
    run: python scripts/sheets_sync.py --csv-only
    stdin: $draft.stdout
