#!/usr/bin/env python3
"""
Deterministic reply classifier for cold-outreach qualification.

No LLM. Keyword / pattern rules map inbound email text to a qualification label
so OpenClaw/Lobster can branch without burning model tokens.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Classification:
    label: str
    rule: str
    confidence: float
    lead_status: str  # CRM status to apply after this reply


# Order matters: first match wins.
RULES: list[tuple[str, str, list[str], str, float]] = [
    # label, rule_id, patterns, lead_status, confidence
    (
        "unsubscribe",
        "opt_out",
        [
            r"\bunsubscribe\b",
            r"\bremove me\b",
            r"\bstop (emailing|contacting)\b",
            r"\bdo not contact\b",
            r"\btake me off\b",
            r"\bopt[- ]?out\b",
        ],
        "suppressed",
        0.99,
    ),
    (
        "ooo",
        "out_of_office",
        [
            r"\bout of (the )?office\b",
            r"\bautomatic reply\b",
            r"\bauto[- ]?reply\b",
            r"\baway from (the )?office\b",
            r"\bi am currently away\b",
            r"\bon leave\b",
        ],
        "contacted",
        0.95,
    ),
    (
        "not_interested",
        "decline",
        [
            r"\bnot interested\b",
            r"\bno thanks\b",
            r"\bno thank you\b",
            r"\bplease pass\b",
            r"\bdon't contact\b",
            r"\bdo not call\b",
            r"\bwe('re| are) all set\b",
            r"\bnot a fit\b",
        ],
        "lost",
        0.95,
    ),
    (
        "meeting",
        "meeting_ask",
        [
            r"\bschedule\b",
            r"\bbook a (call|meeting)\b",
            r"\bset up a (call|meeting)\b",
            r"\bcalendly\b",
            r"\bavailable (on|at|this|next)\b",
            r"\blet's (meet|hop on|jump on)\b",
        ],
        "won",
        0.9,
    ),
    (
        "interested",
        "positive_interest",
        [
            r"\binterested\b",
            r"\btell me more\b",
            r"\bsend (more )?info\b",
            r"\bpricing\b",
            r"\bhow much\b",
            r"\blet's talk\b",
            r"\bsounds good\b",
            r"\byes[,.]?\s+(please|i'd|interested)\b",
        ],
        "replied",
        0.85,
    ),
    (
        "question",
        "clarifying_question",
        [
            r"\bwho (are|is) (you|this)\b",
            r"\bhow does (this|it) work\b",
            r"\bwhat (exactly )?do you\b",
            r"\?",
        ],
        "replied",
        0.7,
    ),
]


def classify_reply(subject: str | None, body: str | None) -> Classification:
    text = f"{subject or ''}\n{body or ''}".lower()
    text = re.sub(r"\s+", " ", text)
    for label, rule_id, patterns, lead_status, conf in RULES:
        for pat in patterns:
            if re.search(pat, text, flags=re.IGNORECASE):
                return Classification(label=label, rule=rule_id, confidence=conf, lead_status=lead_status)
    return Classification(label="unclear", rule="no_match", confidence=0.4, lead_status="replied")
