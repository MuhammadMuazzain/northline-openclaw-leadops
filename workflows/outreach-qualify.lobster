name: outreach-qualify
description: Preview then approval-gated send of cold outreach drafts via Workspace gog.
args:
  limit:
    default: "5"
  dry_run:
    default: "true"
steps:
  - id: preview
    env:
      LIMIT: "$LOBSTER_ARG_LIMIT"
    run: python scripts/send_outreach.py --limit "$LIMIT"

  - id: approve_send
    approval: Send these cold outreach emails via Gmail (gog)? Review recipients first.
    stdin: $preview.stdout

  - id: execute
    env:
      LIMIT: "$LOBSTER_ARG_LIMIT"
    run: python scripts/send_outreach.py --limit "$LIMIT" --execute
    stdin: $preview.stdout
    when: $approve_send.approved
