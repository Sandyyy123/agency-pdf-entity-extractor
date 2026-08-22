"""
Validation gates -- the layer that stops bad data becoming a trusted record.

"Valid JSON does not mean correct data." These gates catch the four failure
modes the client called out:
  1. Hallucinated values   -> every value must trace to a source span (provenance).
  2. Silent omissions      -> required fields and row counts are asserted.
  3. Incorrect relationships -> role's person must exist in the people set.
  4. Ambiguous data        -> low-confidence / LLM rows are flagged NEEDS_REVIEW,
                              never auto-accepted.
"""
from __future__ import annotations

import re

from .schemas import (
    ExtractionMethod,
    ExtractionResult,
    ReviewState,
)

AUTO_ACCEPT_MIN_CONFIDENCE = 0.85


def grounding_check(result: ExtractionResult) -> list[str]:
    """Every value must be grounded in a non-empty source span (anti-hallucination)."""
    problems: list[str] = []
    for p in result.people:
        if not p.provenance.raw_text.strip():
            problems.append(f"person '{p.full_name}' has no source span (possible hallucination)")
    for proj in result.projects:
        if not proj.provenance.raw_text.strip():
            problems.append(f"project '{proj.title}' has no source span (possible hallucination)")
    return problems


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def relationship_check(result: ExtractionResult) -> list[str]:
    """Every role must reference a person that actually exists in the people set."""
    known = {_norm_name(p.full_name) for p in result.people}
    problems: list[str] = []
    for proj in result.projects:
        for r in proj.roles:
            if _norm_name(r.person_name) not in known:
                problems.append(
                    f"project '{proj.title}' role '{r.role}' references unknown "
                    f"person '{r.person_name}' (broken relationship)"
                )
    return problems


def completeness_check(result: ExtractionResult, expected_projects: int | None = None) -> list[str]:
    """Guard against silent omissions when we know how many records to expect."""
    problems: list[str] = []
    if expected_projects is not None and len(result.projects) != expected_projects:
        problems.append(
            f"silent omission: expected {expected_projects} projects, "
            f"extracted {len(result.projects)}"
        )
    for proj in result.projects:
        if not proj.roles:
            problems.append(f"project '{proj.title}' has zero roles (check parser coverage)")
    return problems


def assign_review_states(result: ExtractionResult) -> dict[str, ReviewState]:
    """Auto-accept only high-confidence deterministic rows; everything else needs review."""
    states: dict[str, ReviewState] = {}
    for p in result.people:
        auto = (
            p.provenance.method == ExtractionMethod.DETERMINISTIC
            and p.provenance.confidence >= AUTO_ACCEPT_MIN_CONFIDENCE
        )
        states[p.entity_id or p.full_name] = (
            ReviewState.AUTO_ACCEPTED if auto else ReviewState.NEEDS_REVIEW
        )
    return states


def validate(result: ExtractionResult, expected_projects: int | None = None) -> dict:
    """Run all gates. Returns a report; raises nothing -- the caller decides."""
    problems = (
        grounding_check(result)
        + relationship_check(result)
        + completeness_check(result, expected_projects)
    )
    states = assign_review_states(result)
    return {
        "passed": len(problems) == 0,
        "problems": problems,
        "review_states": {k: v.value for k, v in states.items()},
        "counts": result.review_summary(),
    }
