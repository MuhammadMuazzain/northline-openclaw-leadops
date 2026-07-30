name: qualify-replies
description: Ingest inbound Gmail (or demo) replies, classify deterministically, update CRM qualification.
args:
  source:
    default: "demo"
  max:
    default: "15"
steps:
  - id: qualify
    env:
      SOURCE: "$LOBSTER_ARG_SOURCE"
      MAX: "$LOBSTER_ARG_MAX"
    run: >
      python scripts/qualify_replies.py
      --source "$SOURCE"
      --max "$MAX"
      --seed-demo-leads
