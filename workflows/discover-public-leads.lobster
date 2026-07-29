name: discover-public-leads
description: Ingest public listing candidates (OpenStreetMap Overpass, sample fallback) into the SQL CRM.
args:
  metro:
    default: "Austin, TX"
  category:
    default: "plumbing"
  limit:
    default: "25"
  source:
    default: "auto"
steps:
  - id: init_crm
    run: python scripts/crm_init.py

  - id: fetch
    env:
      METRO: "$LOBSTER_ARG_METRO"
      CATEGORY: "$LOBSTER_ARG_CATEGORY"
      LIMIT: "$LOBSTER_ARG_LIMIT"
      SOURCE: "$LOBSTER_ARG_SOURCE"
    run: >
      python scripts/fetch_public_listings.py
      --metro "$METRO"
      --category "$CATEGORY"
      --limit "$LIMIT"
      --source "$SOURCE"

  - id: done
    run: >
      python -c "import json,sys; print(json.dumps({'ok':True,'step':'discover-public-leads'}))"
