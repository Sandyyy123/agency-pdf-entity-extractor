"""
Entity resolution and deduplication.

The hard part of this domain is not producing JSON -- it is making sure "Jane
Doe", "Jane  Doe" and "J. Doe <jane@x.com>" collapse to ONE person, while two
genuinely different people who happen to share a name do NOT. We resolve on a
blocking key + a similarity score, and we NEVER auto-merge across a strong
disambiguator (a different confirmed email).
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from .schemas import Company, ExtractionResult, Person, Project


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[.\-_]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _stable_id(prefix: str, key: str) -> str:
    return f"{prefix}_{hashlib.sha1(key.encode()).hexdigest()[:10]}"


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def resolve_people(people: list[Person], threshold: float = 0.90) -> tuple[list[Person], list[str]]:
    """Merge duplicate people. Returns (merged_people, notes)."""
    merged: list[Person] = []
    notes: list[str] = []

    for p in people:
        match = None
        for existing in merged:
            # Strong signal: same non-empty email -> definitely same person.
            if p.contact.email and existing.contact.email:
                if p.contact.email == existing.contact.email:
                    match = existing
                    break
                # Different confirmed emails -> block the merge even if names match.
                if _name_similarity(p.full_name, existing.full_name) >= threshold:
                    notes.append(
                        f"kept '{p.full_name}' and '{existing.full_name}' separate: "
                        f"same name but different emails "
                        f"({p.contact.email} vs {existing.contact.email})"
                    )
                continue
            if _name_similarity(p.full_name, existing.full_name) >= threshold:
                match = existing
                break

        if match is None:
            p.entity_id = _stable_id("person", p.contact.email or _norm(p.full_name))
            merged.append(p)
        else:
            # Fill missing contact fields from the duplicate; keep highest confidence provenance.
            if not match.contact.email and p.contact.email:
                match.contact.email = p.contact.email
            if not match.contact.phone and p.contact.phone:
                match.contact.phone = p.contact.phone
            if p.provenance.confidence > match.provenance.confidence:
                match.provenance = p.provenance
            notes.append(f"merged duplicate person '{p.full_name}' -> {match.entity_id}")

    return merged, notes


def resolve_companies(companies: list[Company], threshold: float = 0.92) -> tuple[list[Company], list[str]]:
    merged: list[Company] = []
    notes: list[str] = []
    for c in companies:
        # Normalize common legal suffixes so "Nike" == "Nike Inc." == "Nike, Inc"
        base = re.sub(r"\b(inc|llc|ltd|gmbh|corp|co)\b\.?", "", _norm(c.name)).strip()
        match = next((e for e in merged
                      if _name_similarity(base, re.sub(r"\b(inc|llc|ltd|gmbh|corp|co)\b\.?", "", _norm(e.name)).strip()) >= threshold),
                     None)
        if match is None:
            c.entity_id = _stable_id("company", base)
            merged.append(c)
        else:
            notes.append(f"merged duplicate company '{c.name}' -> {match.entity_id}")
    return merged, notes


def link_projects_to_ids(result: ExtractionResult) -> None:
    """Attach entity_ids to project.client_company references after resolution."""
    company_index = {_norm(c.name): c.entity_id for c in result.companies}
    for proj in result.projects:
        proj.entity_id = _stable_id("project", _norm(proj.title))
        if proj.client_company:
            proj.client_company = company_index.get(_norm(proj.client_company), proj.client_company)


def resolve_all(result: ExtractionResult) -> ExtractionResult:
    result.people, pnotes = resolve_people(result.people)
    result.companies, cnotes = resolve_companies(result.companies)
    link_projects_to_ids(result)
    result.warnings.extend(pnotes + cnotes)
    return result
