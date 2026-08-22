"""
Extraction accuracy + regression tests.

These are the tests the job asks for: they lock in dedup behaviour, the
"same name / different email -> keep separate" rule, relationship integrity,
and the anti-hallucination grounding gate.
"""
from pathlib import Path

import pytest

from extractor import run_pipeline
from extractor.deterministic import parse_agency_sheet
from extractor.entity_resolution import resolve_people
from extractor.schemas import Contact, ExtractionMethod, Person, Provenance
from extractor.validation import grounding_check, relationship_check

SAMPLE = Path(__file__).parent.parent / "sample_data" / "sample_agency_sheet.txt"


@pytest.fixture(scope="module")
def pipeline():
    text = SAMPLE.read_text(encoding="utf-8")
    return run_pipeline(text, source_file=SAMPLE.name, expected_projects=3)


def test_extracts_all_projects(pipeline):
    result, report = pipeline
    assert len(result.projects) == 3
    assert report["passed"] is True   # completeness gate satisfied


def test_dedups_person_by_email(pipeline):
    result, _ = pipeline
    # "Mara Velez" appears twice with the same email -> exactly one person.
    maras = [p for p in result.people if p.full_name.lower().replace("  ", " ") == "mara velez"]
    assert len(maras) == 1
    # merged record keeps the phone that only one of the two rows had
    assert maras[0].contact.phone is not None


def test_keeps_same_name_different_email_separate(pipeline):
    result, _ = pipeline
    # Two different "Jordan Lee" people with different emails must NOT be merged.
    jordans = [p for p in result.people if p.full_name.lower() == "jordan lee"]
    assert len(jordans) == 2
    assert len({j.contact.email for j in jordans}) == 2


def test_dedups_company_with_legal_suffix_variants(pipeline):
    result, _ = pipeline
    # "Northwind Apparel Inc." and "Northwind Apparel, Inc" -> one company.
    northwinds = [c for c in result.companies if "northwind" in c.name.lower()]
    assert len(northwinds) == 1


def test_relationships_are_intact(pipeline):
    result, _ = pipeline
    assert relationship_check(result) == []


def test_grounding_rejects_hallucinated_person():
    # A person with an empty source span must be flagged (anti-hallucination).
    ghost = Person(
        full_name="Nobody Real",
        contact=Contact(),
        provenance=Provenance(
            source_file="x", raw_text="   ",
            method=ExtractionMethod.LLM, confidence=0.9,
        ),
    )
    from extractor.schemas import ExtractionResult
    res = ExtractionResult(people=[ghost])
    problems = grounding_check(res)
    assert any("hallucination" in p for p in problems)


def test_resolution_notes_report_the_block():
    # Direct unit test of the "same name, different email" branch.
    a = Person(full_name="Alex Kim", contact=Contact(email="a@x.com"),
               provenance=Provenance(source_file="f", raw_text="Alex Kim",
                                     method=ExtractionMethod.DETERMINISTIC, confidence=1.0))
    b = Person(full_name="Alex Kim", contact=Contact(email="b@x.com"),
               provenance=Provenance(source_file="f", raw_text="Alex Kim",
                                     method=ExtractionMethod.DETERMINISTIC, confidence=1.0))
    merged, notes = resolve_people([a, b])
    assert len(merged) == 2
    assert any("different emails" in n for n in notes)
