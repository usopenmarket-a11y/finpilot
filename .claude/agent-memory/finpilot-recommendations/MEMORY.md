# Recommendations Agent Memory Index

## Project

- [M6 input model bridge pattern](project_m6_input_model_bridge.md) — Why monthly_plan.py and forecaster.py define their own Pydantic input models instead of importing analytics dataclasses; covers field-name mapping from analytics layer to recommendation contract
- [Confidence scoring heuristics](project_confidence_scoring.md) — Confidence score values used in monthly_plan.py and forecaster.py and the rationale for sparse-data thresholds and per-month decay
- [M6 debt optimizer and savings detector](project_m6_modules.md) — Constants, confidence rules, and design decisions for debt_optimizer.py and savings.py; snowball/avalanche recommendation logic and savings opportunity detection thresholds
