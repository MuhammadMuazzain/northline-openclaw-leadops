name: discover-public-leads
description: Ingest public listing candidates for a metro/category into the SQL CRM.
args:
  metro:
    default: "Austin, TX"
  category:
    default: "hvac"
  limit:
    default: "25"
steps:
  - id: init_crm
    run: python scripts/crm_init.py

  - id: fetch
    env:
      METRO: "$LOBSTER_ARG_METRO"
      CATEGORY: "$LOBSTER_ARG_CATEGORY"
      LIMIT: "$LOBSTER_ARG_LIMIT"
    run: >
      python scripts/fetch_public_listings.py
      --metro "$METRO"
      --category "$CATEGORY"
      --limit "$LIMIT"

  - id: done
    run: >
      python -c "import json,sys; print(json.dumps({'ok':True,'step':'discover-public-leads'}))"
