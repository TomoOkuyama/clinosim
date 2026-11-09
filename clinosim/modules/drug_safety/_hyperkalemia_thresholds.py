"""Algorithm constants of the inpatient hyperkalemia response (Issue #2981).

The clinical threshold, the held drug classes and the order sets are data
(``reference_data/hyperkalemia_response.yaml``); this module keeps only the
timing constant of the order placement.
"""

from __future__ import annotations

__all__ = ["TREATMENT_ORDER_DELAY_MIN"]

TREATMENT_ORDER_DELAY_MIN: int = 15
"""Minutes from the potassium result to the hyperkalemia treatment orders.
Unit: minutes. Rationale: clinosim modelling choice — a critical potassium is
phoned to the ward and acted on promptly, so the orders follow the result by
a short interval rather than carrying the result's own timestamp."""
