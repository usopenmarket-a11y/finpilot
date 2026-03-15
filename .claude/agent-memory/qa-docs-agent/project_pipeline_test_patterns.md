---
name: Pipeline test patterns
description: Mock strategy, call-counter pattern, and fixture structure for ETL pipeline tests (normalizer/deduplicator/upserter/runner)
type: project
---

## Test file location
`apps/api/app/tests/test_pipeline.py` — 21 tests, all passing.

## Key mock pattern: Supabase fluent builder

The pipeline calls `supabase.table(name).select(...).eq(...).execute()` and
`supabase.table(name).upsert(...).execute()` and `.insert(...).execute()`.
Each test stubs this chain with a `MagicMock` builder whose `.execute` is an
`AsyncMock` returning a `MagicMock` with `.data` and `.count` set explicitly.

```python
builder = MagicMock()
execute_result = MagicMock()
execute_result.data = [{"id": str(some_uuid)}]
builder.execute = AsyncMock(return_value=execute_result)
builder.upsert = MagicMock(return_value=builder)
supabase.table = MagicMock(return_value=builder)
```

## Critical: runner calls `table("transactions")` twice

`run_pipeline()` calls `table("transactions")` twice in sequence:
1. SELECT query in `filter_new_transactions()` (deduplication)
2. INSERT query in `insert_transactions()` (persistence)

The mock factory must use a **shared counter outside the per-builder closure**
so the counter does not reset between the two calls. The pattern used:

```python
txn_call_counter: dict[str, int] = {"n": 0}

def _table_factory(table_name: str) -> MagicMock:
    if table_name == "transactions":
        txn_call_counter["n"] += 1
        this_call = txn_call_counter["n"]
        # this_call == 1 -> configure SELECT response
        # this_call == 2 -> configure INSERT response with .count set to int
```

**Why:** a per-builder counter (inside the closure) always starts at 0 on each
`table()` call, so the INSERT builder always hits the SELECT branch. The shared
dict avoids this.

## Fixture helpers defined at module level

- `make_scraper_result(bank_name, n_transactions)` — builds a `ScraperResult`
  with `n` unique `Transaction` objects (external_id `"TXN-{i:04d}"`).
- `mock_supabase_client()` — generic Supabase stub for non-runner tests; uses
  `side_effect=lambda _name: _make_builder()` so each table call gets a fresh
  builder. Not suitable for runner tests (use `_make_pipeline_supabase` there).

## Normalizer: model_copy pattern for override

Source models are Pydantic v2 — use `.model_copy(update={...})` to mutate a
field value for a specific test case rather than constructing from scratch:

```python
raw_account = raw_account.model_copy(update={"currency": "egp"})
```

## Coverage

All four modules fully covered by the 21 tests:
- `normalizer.py`: 8 tests covering all transformations + empty list branch
- `deduplicator.py`: 4 tests — empty DB, partial overlap, full overlap, empty input
- `upserter.py`: 5 tests — table name, UUID return, transaction table, count, empty short-circuit
- `runner.py`: 4 tests — happy path, partial dedup math, all-deduped, dataclass fields

## supabase package

Not installed in the venv by default. Install with:
```bash
/home/fady_/.local/bin/uv pip install "supabase>=2.0.0"
```
Version installed: 2.28.2 (as of 2026-03-16).
