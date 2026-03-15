"""ETL pipeline for FinPilot.

Coordinates transformation of raw ScraperResult into clean, deduplicated,
validated database records. Organized into stages:

1. Normalizer: Cleans and standardizes raw scraped data
2. Deduplicator: Prevents double-inserts via (account_id, external_id)
3. Upserter: Persists to Supabase with conflict resolution
4. Runner: Orchestrates the full pipeline

Public API:
- run_pipeline: Main entry point
- PipelineRunResult: Result dataclass
- normalize: Normalization function
- NormalizedResult: Normalized data container
"""

from __future__ import annotations

from app.pipeline.normalizer import (
    NormalizedResult,
    normalize,
)
from app.pipeline.runner import (
    PipelineRunResult,
    run_pipeline,
)

__all__ = [
    "run_pipeline",
    "PipelineRunResult",
    "normalize",
    "NormalizedResult",
]
