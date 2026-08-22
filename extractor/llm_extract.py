"""
LLM extraction -- used ONLY for free-text where structure is unreliable.

Two guardrails make LLM output safe to store:
  1. Structured output: the model is constrained to a JSON schema (here via a
     pydantic model). Malformed output is rejected, not stored.
  2. Grounding: the extractor is told to copy spans verbatim and to return the
     source substring for each value. If a returned value is not found in the
     source text, we drop it as a probable hallucination.

Runs in DEMO MODE with no API key: a tiny rule-based stand-in produces the same
schema so the pipeline is runnable end-to-end without credentials.
"""
from __future__ import annotations

import os
import re

from .schemas import ExtractionMethod, Person, Contact, Provenance

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _grounded(value: str, source: str) -> bool:
    """Anti-hallucination: the value must appear in the source text."""
    return value.strip().lower() in source.lower()


def extract_people_from_notes(notes: str, source_file: str) -> list[Person]:
    """
    Extract people mentioned in a free-text note block.

    With OPENAI_API_KEY set, swap the demo block for a real structured call
    (response_format=json_schema). The grounding filter below stays identical --
    that is what keeps LLM output trustworthy.
    """
    people: list[Person] = []

    if os.getenv("OPENAI_API_KEY"):
        # Real call would go here; kept out of the demo so the repo runs offline.
        raw_candidates = _demo_llm(notes)   # replace with model output
    else:
        raw_candidates = _demo_llm(notes)

    for cand in raw_candidates:
        name = cand["full_name"]
        # Drop anything the model returned that is not literally in the source.
        if not _grounded(name, notes):
            continue
        email = cand.get("email")
        if email and not _grounded(email, notes):
            email = None
        people.append(
            Person(
                full_name=name,
                contact=Contact(email=email),
                provenance=Provenance(
                    source_file=source_file, page=None, line=None,
                    raw_text=name, method=ExtractionMethod.LLM,
                    confidence=0.6,   # LLM rows never auto-accept (< 0.85 gate)
                ),
            )
        )
    return people


def _demo_llm(notes: str) -> list[dict]:
    """Deterministic stand-in for a structured LLM call, for offline demos."""
    out: list[dict] = []
    # naive: capitalized two-word sequences followed optionally by an email
    for m in re.finditer(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b", notes):
        name = m.group(1)
        tail = notes[m.end():m.end() + 60]
        email_m = EMAIL_RE.search(tail)
        out.append({"full_name": name, "email": email_m.group(0) if email_m else None})
    return out
