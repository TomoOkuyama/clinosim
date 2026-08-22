"""clinosim — Clinically Realistic Hospital Data Simulator.

Programmatic API surface (Issue #554):

* :mod:`clinosim.api` — pinned public surface (recommended import path).
  Symbols exported there are guaranteed stable across MINOR releases; removals
  require a MAJOR bump. See :doc:`docs/roadmap.md` for change tracking.
* :mod:`clinosim.simulator` — patient-encounter simulator entry points.
* :mod:`clinosim.audit` — per-Module PR gate.
* :mod:`clinosim.eval` — cohort-scoring framework.
* :mod:`clinosim.codes` — coding-system registry.
* :mod:`clinosim.dataset` — cohort loading utilities.

Any symbol prefixed with ``_`` is internal even when it appears in a
technically-importable module. Underscore names may be renamed, removed, or
have their behaviour changed in any release; downstream code should reach only
for names re-exported from ``clinosim.api``.
"""

__version__ = "0.3.0"
__all__ = ["__version__"]
