"""SpO2 hypoxemia thresholds for oxygen therapy triggers (Issue #561).

Clinical citations:

- ``SPO2_HYPOXEMIA_TRIGGER`` (92%) — standard ward-level oxygen-therapy
  initiation threshold in adult inpatients without chronic hypercapnic COPD
  (WHO / ATS clinical practice guidelines; JRS 酸素療法ガイドライン matches
  this cutoff for the general inpatient population).
- ``SPO2_SEVERE_HYPOXEMIA`` (88%) — non-rebreather / high-flow escalation
  trigger. Represents severe hypoxemia where nasal-cannula low-flow is
  insufficient (BTS emergency oxygen guideline). Below this the nursing
  pipeline records a higher-flow device.

Both values were previously bare literals inside
``clinosim/simulator/vitals_pipeline.py``.
"""

from __future__ import annotations

__all__ = [
    "SPO2_HYPOXEMIA_TRIGGER",
    "SPO2_SEVERE_HYPOXEMIA",
]

SPO2_HYPOXEMIA_TRIGGER: int = 92
"""SpO2 (%) at or below which routine ward oxygen therapy is initiated."""

SPO2_SEVERE_HYPOXEMIA: int = 88
"""SpO2 (%) at or below which non-rebreather / high-flow oxygen is used."""
