#!/usr/bin/env python3
"""
Runnable demo of the agency-PDF extraction pipeline.

    python main.py                          # runs on the bundled sample sheet
    python main.py path/to/extracted.txt    # runs on your own extracted PDF text

In production, the text argument is the output of a PDF text/layout extractor
(pdfplumber / PyMuPDF / Azure Document Intelligence). This demo takes the text
directly so it is fully runnable offline with no PDF or cloud dependency.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from extractor import run_pipeline

SAMPLE = Path(__file__).parent / "sample_data" / "sample_agency_sheet.txt"


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else SAMPLE
    text = src.read_text(encoding="utf-8")

    # We "know" the sheet has 3 projects -> pass it so the completeness gate can
    # catch a silent omission if the parser under-extracts.
    result, report = run_pipeline(text, source_file=src.name, expected_projects=3)

    print("=" * 70)
    print(f"SOURCE: {src.name}")
    print("=" * 70)
    print("\nSTRUCTURED OUTPUT (relationships preserved):\n")
    for proj in result.projects:
        print(f"  PROJECT  {proj.title}  [{proj.entity_id}]")
        print(f"           client={proj.client_company}  start={proj.start_date}")
        for r in proj.roles:
            print(f"             - {r.role}: {r.person_name}")
    print("\nRESOLVED PEOPLE (deduplicated):\n")
    for p in result.people:
        print(f"  {p.entity_id}  {p.full_name:<14} {p.contact.email or '-'}")
    print("\nRESOLVED COMPANIES (deduplicated):\n")
    for c in result.companies:
        print(f"  {c.entity_id}  {c.name}")

    print("\n" + "-" * 70)
    print("VALIDATION REPORT")
    print("-" * 70)
    print(json.dumps(report, indent=2))
    if result.warnings:
        print("\nENTITY-RESOLUTION NOTES:")
        for w in result.warnings:
            print(f"  * {w}")

    # Exit non-zero if a validation gate failed -> usable in CI / regression tests.
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
