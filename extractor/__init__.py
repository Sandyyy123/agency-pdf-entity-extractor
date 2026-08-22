"""Agency PDF -> structured relational data extraction pipeline."""
from .deterministic import parse_agency_sheet
from .entity_resolution import resolve_all
from .validation import validate
from .schemas import ExtractionResult

__all__ = ["parse_agency_sheet", "resolve_all", "validate", "ExtractionResult", "run_pipeline"]


def run_pipeline(text: str, source_file: str, page: int | None = None,
                 expected_projects: int | None = None) -> tuple[ExtractionResult, dict]:
    """End-to-end: parse -> resolve/dedup -> validate. Returns (result, report)."""
    result = parse_agency_sheet(text, source_file=source_file, page=page)
    result = resolve_all(result)
    report = validate(result, expected_projects=expected_projects)
    return result, report
