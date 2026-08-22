"""
Pydantic schemas for the extraction pipeline.

Every extracted entity carries provenance (where it came from) and a review
state (whether a human has confirmed it). This is the backbone of the rule
"valid JSON does not mean correct data": nothing becomes a trusted record until
it passes validation AND, for low-confidence rows, human review.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ExtractionMethod(str, Enum):
    DETERMINISTIC = "deterministic"   # parsed from reliable document structure
    LLM = "llm"                       # contextual interpretation, needs stricter validation
    HUMAN = "human"                   # entered/corrected by a reviewer


class ReviewState(str, Enum):
    AUTO_ACCEPTED = "auto_accepted"   # deterministic + passed all validators
    NEEDS_REVIEW = "needs_review"     # low confidence or LLM-sourced
    CONFIRMED = "confirmed"           # a human signed off
    REJECTED = "rejected"


class Provenance(BaseModel):
    """Traceability for a single extracted value."""
    source_file: str
    page: Optional[int] = None
    line: Optional[int] = None
    raw_text: str = Field(..., description="The exact source span the value came from")
    method: ExtractionMethod
    confidence: float = Field(..., ge=0.0, le=1.0)


class Contact(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError(f"implausible email: {v!r}")
        return v

    @field_validator("phone")
    @classmethod
    def _phone_shape(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        digits = [c for c in v if c.isdigit()]
        if len(digits) < 7:
            raise ValueError(f"implausible phone: {v!r}")
        return v


class Person(BaseModel):
    entity_id: Optional[str] = None      # assigned during entity resolution
    full_name: str
    contact: Contact = Field(default_factory=Contact)
    provenance: Provenance

    @field_validator("full_name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        import re
        if not v or not v.strip():
            raise ValueError("empty person name")
        return re.sub(r"\s+", " ", v).strip()


class Company(BaseModel):
    entity_id: Optional[str] = None
    name: str
    provenance: Provenance


class ProjectRole(BaseModel):
    """A person assigned to a role on a project (the relationship that matters)."""
    person_name: str
    role: str
    provenance: Provenance


class Project(BaseModel):
    entity_id: Optional[str] = None
    title: str
    client_company: Optional[str] = None
    start_date: Optional[str] = None
    roles: list[ProjectRole] = Field(default_factory=list)
    provenance: Provenance


class ExtractionResult(BaseModel):
    """The full structured output for one source document."""
    projects: list[Project] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    companies: list[Company] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def review_summary(self) -> dict:
        return {
            "projects": len(self.projects),
            "people": len(self.people),
            "companies": len(self.companies),
            "warnings": len(self.warnings),
        }
