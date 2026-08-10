"""Forced-scenario (``run_forced`` / ``clinosim test-disease``) thresholds (Issue #637).

Lifts the previously-inline literals used only inside
:func:`clinosim.simulator.engine.run_forced` — the QA / documentation
code path invoked by ``clinosim test-disease`` and downstream unit
tests. These values do NOT affect the population simulator
(``clinosim simulate``); they parameterize the synthetic single-patient
scenarios used to reproduce specific disease trajectories.

Empirical tuning notes: the forced-scenario path is deliberately
reproducible — hardcoded reference year, event date, and severity
fraction map so any two ``run_forced`` calls with the same
(seed, disease_id, count, archetype) produce identical output. Do
NOT re-tune these to match live-cohort statistics; that would break
the "identical inputs → identical outputs" contract that the QA
harness relies on.
"""

from __future__ import annotations

from datetime import date

__all__ = [
    "FORCED_SCENARIO_AGE_MAX_EXCLUSIVE",
    "FORCED_SCENARIO_AGE_MIN",
    "FORCED_SCENARIO_DEFAULT_AGE",
    "FORCED_SCENARIO_DEFAULT_SEVERITY",
    "FORCED_SCENARIO_DEFAULT_SEX",
    "FORCED_SCENARIO_EVENT_DATE",
    "FORCED_SCENARIO_REFERENCE_YEAR",
    "FORCED_SCENARIO_SEVERITY_FRACTIONS",
    "FORCED_SCENARIO_SEVERITY_FRACTION_FALLBACK",
]


# ---------------------------------------------------------------------------
# Patient synthesis when scenario.patient_overrides is empty
# ---------------------------------------------------------------------------

FORCED_SCENARIO_AGE_MIN: int = 55
"""Inclusive lower bound of the uniform-random age draw used when the
scenario does not pin an age.

Empirical tuning for the synthetic simulator: 55 targets the
older-adult population where clinosim's modeled diseases predominate
— matches the age skew of the JP-CLINS acute-inpatient cohort."""

FORCED_SCENARIO_AGE_MAX_EXCLUSIVE: int = 95
"""Exclusive upper bound of the uniform-random age draw (``np.random.
Generator.integers`` treats ``high`` as exclusive). Combined with
:data:`FORCED_SCENARIO_AGE_MIN` this yields ages in ``[55, 94]``."""

FORCED_SCENARIO_DEFAULT_AGE: int = 72
"""Fallback age used when ``scenario.patient_overrides`` is provided
but lacks an ``age`` key.

Empirical tuning for the synthetic simulator: 72 sits near the mean
of the ``[55, 95)`` random-draw range and matches the modal age of
the JP-CLINS acute-inpatient cohort."""

FORCED_SCENARIO_DEFAULT_SEX: str = "F"
"""Fallback sex used when ``scenario.patient_overrides`` is provided
but lacks a ``sex`` key. Chosen arbitrarily; the forced-scenario harness
does not depend on this default because callers that care about sex
always set it explicitly."""


# ---------------------------------------------------------------------------
# Event / trajectory pinning — reproducibility-focused
# ---------------------------------------------------------------------------

FORCED_SCENARIO_REFERENCE_YEAR: int = 2024
"""Reference year used to construct the synthetic ``date_of_birth``
(``date(REFERENCE_YEAR - age, 1, 1)``).

Empirical tuning for the synthetic simulator: pinned so ``run_forced``
outputs are reproducible across time — a floating ``today().year``
would silently shift birth dates and downstream age-derived fields
on every rerun."""

FORCED_SCENARIO_EVENT_DATE: date = date(2024, 6, 15)
"""Hardcoded life-event timestamp for the forced scenario. Same
reproducibility rationale as :data:`FORCED_SCENARIO_REFERENCE_YEAR`
— mid-2024, mid-year to sit far from any month/quarter/year
boundary that could interact with seasonal / calendar-based
enrichers."""

FORCED_SCENARIO_DEFAULT_SEVERITY: str = "moderate"
"""Fallback severity label when ``scenario.severity`` is None. Matches
the ``moderate`` key in :data:`FORCED_SCENARIO_SEVERITY_FRACTIONS`."""

FORCED_SCENARIO_SEVERITY_FRACTIONS: dict[str, float] = {
    "mild": 0.2,
    "moderate": 0.5,
    "severe": 0.8,
}
"""Mapping from severity label to the ``LifeEvent.severity`` scalar
fraction consumed downstream by the physiology model.

Empirical tuning for the synthetic simulator: 0.2 / 0.5 / 0.8 span
roughly a full standard deviation around the population midpoint and
match the same mapping used by the population simulator when it
resolves a severity label at life-event creation time."""

FORCED_SCENARIO_SEVERITY_FRACTION_FALLBACK: float = 0.5
"""Fraction used when the severity label is not in
:data:`FORCED_SCENARIO_SEVERITY_FRACTIONS` — falls back to the
``moderate`` value so an unknown label degrades to the middle of the
range rather than crashing or defaulting to zero."""
