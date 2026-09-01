> **⚠️ Proprietary — All Rights Reserved.** © 2026 Sandeep Grover. This repository is licensed to Sandeep Grover and may **not** be used, run, copied, modified, distributed, or used to train models without prior written permission. Public visibility does not grant a license. See [LICENSE](LICENSE).

---

# agency-pdf-entity-extractor

A small, **runnable** reference pipeline for the hard part of document-extraction
projects: turning messy agency PDFs into **trustworthy relational data** —
projects, people, companies and roles — with deduplication, entity resolution,
source provenance, review states, and validation gates that stop bad data from
becoming a trusted record.

Built as a demo of the approach for a talent-management ingestion MVP. It runs
offline with no PDF, no LLM key, and no database required.

> **Core principle:** *valid JSON does not mean correct data.* Every value is
> grounded in a source span, every relationship is checked, low-confidence rows
> are flagged for review, and duplicates are resolved without silently merging
> two different people who happen to share a name.

## Architecture

```
   PDF (multi-page)
        │  pdfplumber / PyMuPDF / Azure DI   (text + layout)
        ▼
  ┌─────────────────────┐     structure reliable?
  │ deterministic parser │◄──────────── yes ─────────────┐
  │ (regex / layout)     │                               │
  └─────────┬───────────┘                                │
            │                     free text / notes only │
            │                              ▼              │
            │                   ┌─────────────────────┐  │
            │                   │ LLM extractor        │  │
            │                   │ structured output +  │  │
            │                   │ grounding filter     │  │
            │                   └─────────┬───────────┘  │
            ▼                             ▼               │
       ┌──────────────────────────────────────────┐      │
       │ entity resolution / dedup                 │      │
       │  - people by email, then fuzzy name       │      │
       │  - block merge on conflicting emails      │      │
       │  - companies by name minus legal suffix   │      │
       └─────────────────┬────────────────────────┘      │
                         ▼                                │
       ┌──────────────────────────────────────────┐      │
       │ validation gates                          │      │
       │  grounding · relationships · completeness │      │
       │  · review-state assignment                │      │
       └─────────────────┬────────────────────────┘      │
                         ▼                                │
       Supabase / PostgreSQL  (provenance + RLS)  ────────┘
                         ▼
                 FastAPI  (lookup · search · review · NL /ask)
```

## Run it

```bash
pip install -r requirements.txt
python main.py                 # runs the bundled sample sheet
pytest -q                      # 7 accuracy / regression tests
uvicorn api.app:app --reload   # then GET /health, /search?q=, /ask?q=
```

## What the sample demonstrates

The bundled sheet is seeded with the traps that break naive extractors:

| Trap in the data | What the pipeline does |
|---|---|
| `Mara Velez` listed twice, same email | Merged into one person; keeps the phone only one row had |
| Two different `Jordan Lee` people, different emails | **Kept separate** — a shared name never forces a merge |
| `Northwind Apparel Inc.` vs `Northwind Apparel, Inc` | Merged (legal-suffix-insensitive) into one company |
| `Mara  Velez` (double space) in a role line | Whitespace-normalized so the relationship still links |
| A person value with no source span | Flagged as a possible hallucination by the grounding gate |
| Ambiguous NL query `"projects for Jordan Lee"` | `/ask` returns candidates and asks to disambiguate — it never guesses |

## The four failure modes this guards against

1. **Hallucinated values** — every value carries a `provenance.raw_text` span; the
   grounding gate rejects anything not found in the source, and LLM output is
   filtered the same way (`extractor/llm_extract.py`).
2. **Silent omissions** — a completeness gate asserts expected record counts and
   flags projects with zero roles (`extractor/validation.py`).
3. **Incorrect relationships** — every role must reference a person that exists in
   the resolved people set.
4. **Ambiguous data** — LLM / low-confidence rows are marked `needs_review`, never
   `auto_accepted`; ambiguous NL references return candidates, not a guess.

## Layout

```
extractor/
  schemas.py            pydantic models + provenance + review states
  deterministic.py      structure-reliable parsing (no LLM)
  llm_extract.py        structured LLM extraction with grounding (offline demo mode)
  entity_resolution.py  people/company dedup + same-name-different-email blocking
  validation.py         grounding / relationship / completeness gates
api/app.py              FastAPI: /projects /search /review /ask
db/schema.sql           Supabase/Postgres schema: provenance, review states, RLS
tests/test_pipeline.py  accuracy + regression tests
sample_data/            illustrative agency sheet (synthetic data only)
```

All names, emails and companies in `sample_data/` are synthetic and illustrative.
