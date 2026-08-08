"""Dehydration thresholds on ``volume_status`` (Issue #561).

``volume_status`` in clinosim's physiology state is a signed normalized
proxy (roughly ``-1.0`` = severe intravascular depletion, ``0.0`` =
euvolemic, ``+1.0`` = volume overload). Below-zero values are increasingly
severe dehydration.

The three thresholds below fire at **different depths of the same axis**
because the physiological effects they trigger are clinically distinct
— they are NOT a single conceptual threshold that got split by accident:

Clinical citations:

- ``BUN_ELEVATION_THRESHOLD`` (−0.3) — mild-to-moderate dehydration. At
  this depth pre-renal azotemia begins to elevate BUN disproportionately
  to serum Cr (BUN:Cr ratio rises past 20:1). Used in
  ``clinosim/modules/physiology/engine.py::_derive_renal_labs`` to add a
  proportional lift on top of the base ``BUN = 15/max(renal, 0.1)`` model.
  Reference: KDIGO acute kidney injury guideline (2012) § 3.3, "pre-renal
  BUN concentrating effect".
- ``HYPERNATREMIA_THRESHOLD`` (−0.35) — severe dehydration with free-water
  deficit. At this depth serum Na begins to rise from the free-water
  deficit effect (hypertonic hypernatremia). Used in
  ``clinosim/modules/physiology/engine.py::apply_coupling_rules`` to lift
  ``sodium_status`` by ``(|volume_status| − 0.35) × 1.2``. Reference:
  Adrogué HJ, Madias NE. "Hypernatremia." N Engl J Med 2000; 342: 1493.

The IV-fluid trigger (``clinosim/modules/observation/fluid_balance.py::
DEHYDRATION_IV_TRIGGER = −0.2``) is a **third** related threshold — it
fires at the mildest depth because it drives a clinical intervention
(start IV) rather than a downstream lab effect. Together the three form
a progression:

- −0.2 (mild): clinician starts IV rehydration
- −0.3 (moderate): BUN begins to rise
- −0.35 (severe): serum Na begins to rise from free-water deficit

The divergence is intentional. Extraction to named constants makes the
progression explicit in the reading experience without collapsing the
three distinct thresholds into one.
"""

from __future__ import annotations

__all__ = [
    "BUN_ELEVATION_THRESHOLD",
    "HYPERNATREMIA_THRESHOLD",
]

BUN_ELEVATION_THRESHOLD: float = -0.3
"""Volume-status cutoff below which pre-renal azotemia lifts BUN
disproportionately (KDIGO 2012 AKI guideline § 3.3)."""

HYPERNATREMIA_THRESHOLD: float = -0.35
"""Volume-status cutoff below which free-water deficit begins to elevate
serum Na (Adrogué & Madias, NEJM 2000; 342: 1493)."""
