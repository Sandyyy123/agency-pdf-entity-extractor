"""
Deterministic parser for agency booking sheets.

Where the document structure is reliable (labeled fields, consistent layout),
we parse with plain Python and regex -- no LLM. Deterministic parsing is
cheaper, faster, fully auditable, and cannot hallucinate a value that is not
literally in the source span. LLM extraction (llm_extract.py) is reserved for
free-text notes where structure is not reliable.
"""
from __future__ import annotations

import re

from .schemas import (
    Company,
    Contact,
    ExtractionMethod,
    Person,
    Project,
    ProjectRole,
    Provenance,
    ExtractionResult,
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")
# "Role: Person <email> / phone" style role lines
ROLE_LINE_RE = re.compile(r"^\s*-\s*(?P<role>[^:]+):\s*(?P<rest>.+?)\s*$")


def _split_records(text: str) -> list[tuple[int, list[tuple[int, str]]]]:
    """Split the sheet into project blocks; keep line numbers for provenance."""
    lines = [(i + 1, ln.rstrip()) for i, ln in enumerate(text.splitlines())]
    blocks: list[tuple[int, list[tuple[int, str]]]] = []
    current: list[tuple[int, str]] = []
    start_line = 0
    for lineno, ln in lines:
        if ln.upper().startswith("PROJECT:"):
            if current:
                blocks.append((start_line, current))
            current = [(lineno, ln)]
            start_line = lineno
        elif current:
            current.append((lineno, ln))
    if current:
        blocks.append((start_line, current))
    return blocks


def _field(block: list[tuple[int, str]], label: str) -> tuple[str, int] | None:
    for lineno, ln in block:
        if ln.upper().startswith(label.upper() + ":"):
            return ln.split(":", 1)[1].strip(), lineno
    return None


def _clean_name(raw: str) -> str:
    """Collapse internal/edge whitespace so names compare consistently."""
    return re.sub(r"\s+", " ", raw).strip()


def parse_agency_sheet(text: str, source_file: str, page: int | None = None) -> ExtractionResult:
    result = ExtractionResult()
    # Collect EVERY person occurrence; deduplication is the resolver's job, not
    # the parser's. Deduping by name here would silently drop two different
    # people who share a name (the exact case the resolver must handle).
    all_people: list[Person] = []
    companies_by_name: dict[str, Company] = {}

    for _, block in _split_records(text):
        title_line = _field(block, "PROJECT")
        if not title_line:
            continue
        title, title_lineno = title_line

        prov_proj = Provenance(
            source_file=source_file, page=page, line=title_lineno,
            raw_text=title, method=ExtractionMethod.DETERMINISTIC, confidence=1.0,
        )

        client = _field(block, "CLIENT")
        start = _field(block, "START")

        project = Project(
            title=title,
            client_company=client[0] if client else None,
            start_date=start[0] if start else None,
            provenance=prov_proj,
        )

        if client:
            cname = client[0]
            if cname and cname.lower() not in companies_by_name:
                companies_by_name[cname.lower()] = Company(
                    name=cname,
                    provenance=Provenance(
                        source_file=source_file, page=page, line=client[1],
                        raw_text=cname, method=ExtractionMethod.DETERMINISTIC,
                        confidence=1.0,
                    ),
                )

        # Role lines within the block, e.g. "- Photographer: Jane Doe <jane@x.com> / +1 555 111 2222"
        in_roles = False
        for lineno, ln in block:
            if ln.upper().startswith("ROLES:"):
                in_roles = True
                continue
            if not in_roles:
                continue
            m = ROLE_LINE_RE.match(ln)
            if not m:
                continue
            role = m.group("role").strip()
            rest = m.group("rest").strip()

            email_m = EMAIL_RE.search(rest)
            phone_m = PHONE_RE.search(rest)
            # Person name = text before the first '<' or email/phone marker
            name = _clean_name(re.split(r"[<(/]", rest, 1)[0])
            if not name:
                result.warnings.append(
                    f"{source_file}:{lineno} role '{role}' has no parseable person name"
                )
                continue

            prov_role = Provenance(
                source_file=source_file, page=page, line=lineno, raw_text=ln.strip(),
                method=ExtractionMethod.DETERMINISTIC, confidence=1.0,
            )
            project.roles.append(ProjectRole(person_name=name, role=role, provenance=prov_role))

            all_people.append(
                Person(
                    full_name=name,
                    contact=Contact(
                        email=email_m.group(0) if email_m else None,
                        phone=phone_m.group(0).strip() if phone_m else None,
                    ),
                    provenance=prov_role,
                )
            )

        result.projects.append(project)

    result.people = all_people
    result.companies = list(companies_by_name.values())
    return result
