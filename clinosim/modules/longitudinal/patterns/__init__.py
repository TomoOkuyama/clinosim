"""Longitudinal pattern registry.

Each pattern provides a `spec` (pydantic model), `step` (per-year
advance), and `initial` (sim-start draw) callable. The engine
dispatches on `AttributeSpec.pattern` through this registry.

Phase 1 ships `ar1` only; Phase 2 adds `markov`, Phase 3 adds `event`.
"""

from __future__ import annotations

from typing import Any

from clinosim.modules.longitudinal.patterns import ar1, event, markov

PATTERN_REGISTRY: dict[str, dict[str, Any]] = {
    "ar1": {
        "spec": ar1.AR1Spec,
        "step": ar1.step,
        "initial": ar1.initial,
    },
    "markov": {
        "spec": markov.MarkovSpec,
        "step": markov.step,
        "initial": markov.initial,
    },
    "event": {
        "spec": event.EventSpec,
        "step": event.step,
        "initial": None,
    },
}


__all__ = ["PATTERN_REGISTRY"]
