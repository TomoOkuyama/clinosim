"""Renal-function thresholds for medication holds and dose adjustments (Issue #561).

``renal_function`` in clinosim's physiology state is a normalized 0.0–1.0
proxy (roughly a health-score / eGFR fraction) — 1.0 = healthy adult baseline,
0.0 = anuric. Threshold values below anchor the drug-holding logic across
the discharge and admission paths.

Clinical citations:

- ``DISCHARGE_RENAL_HOLD_THRESHOLD`` (0.3) — corresponds to KDIGO CKD stage
  3b+ (eGFR <45 mL/min/1.73m²) or an active AKI equivalent. Below this the
  discharge Rx builder withholds any drug from :data:`_RENAL_HOLD_DRUGS`
  (see ``clinosim/simulator/discharge_rx.py``): metformin, spironolactone,
  and similar nephrotoxic / renally-cleared agents.
- ``METFORMIN_ADMISSION_HOLD_THRESHOLD`` (0.4) — slightly more conservative
  than the discharge threshold; on admission the medication pipeline holds
  metformin at initial_renal <0.4 to avoid lactic-acidosis risk during
  contrast studies or acute illness (FDA metformin label + JDS guideline).
- ``METFORMIN_RENAL_RESERVE_THRESHOLD`` (0.5) — a second guard on top of the
  admission threshold; used with ``has_renal_impairment`` to catch borderline
  patients whose initial value passed but whose reserve is low (repeated-dose
  safety margin).

These three values are intentionally different — reconciling them into a
single canonical threshold would be a data-quality decision (not byte-neutral)
and is deferred to a follow-up Issue.
"""

from __future__ import annotations

__all__ = [
    "DISCHARGE_RENAL_HOLD_THRESHOLD",
    "METFORMIN_ADMISSION_HOLD_THRESHOLD",
    "METFORMIN_RENAL_RESERVE_THRESHOLD",
]

DISCHARGE_RENAL_HOLD_THRESHOLD: float = 0.3
"""KDIGO stage 3b+ / active AKI proxy — discharge Rx withholds nephrotoxic drugs."""

METFORMIN_ADMISSION_HOLD_THRESHOLD: float = 0.4
"""On admission, metformin is held when ``initial_renal < 0.4`` (FDA label
guidance for reduced renal function during hospitalization)."""

METFORMIN_RENAL_RESERVE_THRESHOLD: float = 0.5
"""Secondary reserve guard applied together with :data:`METFORMIN_ADMISSION_HOLD_THRESHOLD`
to catch borderline patients."""
