# QA & Docs Agent Memory Index

| File | Type | Description |
|------|------|-------------|
| [project_test_structure.md](project_test_structure.md) | project | Test file layout, conftest fixture, pyproject.toml config for the API suite |
| [project_model_patterns.md](project_model_patterns.md) | project | Key model fields, defaults, and validation constraints in db.py and api.py |
| [project_health_endpoint.md](project_health_endpoint.md) | project | Verified shape and routing of the /api/v1/health endpoint |
| [project_crypto_module.md](project_crypto_module.md) | project | Coverage baseline, unreachable lines, and mock patterns for app/crypto.py tests |
| [project_scraper_test_patterns.md](project_scraper_test_patterns.md) | project | Playwright mock chain, error-selector discrimination, and page.content() call counts for NBE/CIB scraper tests |
| [project_pipeline_test_patterns.md](project_pipeline_test_patterns.md) | project | Supabase builder mock, shared call-counter for runner's dual transactions-table calls, fixture factories for ETL pipeline tests |
| [project_analytics_test_patterns.md](project_analytics_test_patterns.md) | project | Fixture factories, Anthropic mock pattern, and key behavioural contracts confirmed by test_analytics.py |
| [project_router_analytics_bug.md](project_router_analytics_bug.md) | project | app/routers/analytics.py imports `compute_trend_report` but function is named `compute_trends` — Backend Agent must fix |
| [project_conftest_lazy_import.md](project_conftest_lazy_import.md) | project | conftest.py defers app.main import into the client fixture to prevent broken router imports from blocking pure-unit test collection |
| [project_test_patterns.md](project_test_patterns.md) | project | Established async mode rules, dual client-fixture pattern (async vs sync TestClient), teardown via clear_storage(), and helper factory conventions |
| [project_debt_router_contract.md](project_debt_router_contract.md) | project | M5 Debt Tracker endpoint contract — settlement logic, schema constraints, required clear_storage() export, and 400/422/404 edge cases |
| [project_recommendations_test_patterns.md](project_recommendations_test_patterns.md) | project | M6 router wire-format gap (transaction_count), savings.py empty-sum bug, mini-app test pattern, and all four module contracts |
