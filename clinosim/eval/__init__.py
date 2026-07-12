"""``clinosim eval`` — public evaluation framework for generated cohorts.

Distinct from ``clinosim audit`` which is the internal per-Module PR gate
(``docs/CONTRIBUTING-modules.md`` "PR 検証ガイド"). ``eval`` scores an
already-generated cohort against three axes — **structural**,
**clinical**, **locale** — producing a numeric score per axis plus a
list of violations, so downstream researchers / ML engineers can grade
their synthetic data before using it.

Public entry points:

- :class:`EvalCheck` / :class:`EvalAxisResult` / :class:`EvalReport` —
  the result dataclasses (see :mod:`clinosim.eval.engine`).
- :class:`EvalEngine` — the orchestrator.
- :func:`add_eval_subparser` / :func:`dispatch_eval` — CLI wiring
  called from :mod:`clinosim.simulator.cli`.

Reports serialise to JSON (machine-readable) and Markdown (human).
"""

from __future__ import annotations

from clinosim.eval.cli import add_eval_subparser, dispatch_eval
from clinosim.eval.engine import (
    EvalAxisResult,
    EvalCheck,
    EvalEngine,
    EvalReport,
    Outcome,
    Severity,
)

__all__ = [
    "EvalCheck",
    "EvalAxisResult",
    "EvalReport",
    "EvalEngine",
    "Outcome",
    "Severity",
    "add_eval_subparser",
    "dispatch_eval",
]
