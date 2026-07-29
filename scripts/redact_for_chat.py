#!/usr/bin/env python3
"""Redact CRM JSON for external / unmonitored chat sessions."""
from __future__ import annotations

import json
import sys

DROP = {"phone", "email", "raw_json", "source_url", "notes", "provider_ref", "body"}


def redact(obj):
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in DROP:
                out[k] = "[redacted]"
            else:
                out[k] = redact(v)
        return out
    return obj


def main() -> int:
    data = json.load(sys.stdin)
    json.dump(redact(data), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
