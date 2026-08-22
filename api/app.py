"""
FastAPI surface for the extraction store.

Endpoints mirror the job spec: project lookup, search, updates (review states),
and an AI-assisted natural-language query that resolves ambiguous references.
The data layer here is an in-memory store seeded from the sample so the API is
runnable without Postgres; swap `STORE` for a Supabase/asyncpg repository in
production (see db/schema.sql for the target schema + RLS).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from extractor import run_pipeline
from extractor.schemas import ReviewState

app = FastAPI(title="Agency Extraction API", version="0.1.0")

# --- seed an in-memory store from the sample sheet -------------------------
_SAMPLE = Path(__file__).parent.parent / "sample_data" / "sample_agency_sheet.txt"
_RESULT, _REPORT = run_pipeline(
    _SAMPLE.read_text(encoding="utf-8"), source_file=_SAMPLE.name, expected_projects=3
)
STORE = {
    "projects": {p.entity_id: p for p in _RESULT.projects},
    "people": {p.entity_id: p for p in _RESULT.people},
    "companies": {c.entity_id: c for c in _RESULT.companies},
    "review": dict(_REPORT["review_states"]),
}


class ReviewUpdate(BaseModel):
    entity_id: str
    state: ReviewState


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "counts": _RESULT.review_summary()}


@app.get("/projects/{project_id}")
def get_project(project_id: str) -> dict:
    proj = STORE["projects"].get(project_id)
    if not proj:
        raise HTTPException(404, f"project {project_id} not found")
    return proj.model_dump()


@app.get("/search")
def search(q: str = Query(..., min_length=1)) -> dict:
    """Case-insensitive substring search across projects, people, companies."""
    ql = q.lower()
    return {
        "projects": [p.model_dump() for p in STORE["projects"].values() if ql in p.title.lower()],
        "people": [p.model_dump() for p in STORE["people"].values() if ql in p.full_name.lower()],
        "companies": [c.model_dump() for c in STORE["companies"].values() if ql in c.name.lower()],
    }


@app.post("/review")
def update_review(update: ReviewUpdate) -> dict:
    known = set(STORE["projects"]) | set(STORE["people"]) | set(STORE["companies"])
    if update.entity_id not in known:
        raise HTTPException(404, f"unknown entity {update.entity_id}")
    STORE["review"][update.entity_id] = update.state.value
    return {"entity_id": update.entity_id, "state": update.state.value}


@app.get("/ask")
def ask(q: str = Query(..., description="natural-language project question")) -> dict:
    """
    Minimal NL query resolver. Demonstrates the ambiguity-handling contract:
    if a name maps to more than one entity, we return the candidates and ask
    for disambiguation rather than guessing (never silently pick one).
    """
    ql = q.lower()
    people_hits = [p for p in STORE["people"].values() if p.full_name.lower() in ql
                   or any(tok in p.full_name.lower() for tok in ql.split())]
    # collapse to distinct names to detect ambiguity
    by_name: dict[str, list] = {}
    for p in people_hits:
        by_name.setdefault(p.full_name.lower(), []).append(p)

    ambiguous = {name: [pp.entity_id for pp in ps] for name, ps in by_name.items() if len(ps) > 1}
    if ambiguous:
        return {
            "answer": None,
            "needs_disambiguation": ambiguous,
            "message": "Multiple people match; specify by email or entity_id.",
        }

    projects = []
    for p in people_hits:
        for proj in STORE["projects"].values():
            if any(r.person_name.lower() == p.full_name.lower() for r in proj.roles):
                projects.append(proj.title)
    return {"answer": sorted(set(projects)) or "no matching projects", "matched_people": [p.entity_id for p in people_hits]}
