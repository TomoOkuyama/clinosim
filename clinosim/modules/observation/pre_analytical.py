"""Pre-analytical error-rate constants for lab specimen handling (Issue #561).

The 4 constants below govern the lab-result simulation loop's pre-analytical
error injection. They were previously duplicated as bare literals at 2 sites
in ``clinosim/simulator/inpatient.py`` (lines 1008-1014 and 1054-1075), so a
tuning change to the specimen-rejection rate silently touched only one
branch. Extracted here so a single edit propagates everywhere.

Clinical citations:

* ``SPECIMEN_REJECTION_RATE`` (0.02, 2%) — CLSI GP26-A4 quality-indicator
  guidance treats ≤2% specimen rejection as an acceptable ceiling for
  routine clinical labs; the simulator uses the guidance ceiling as a
  representative background rate (aggregate across hemolysis, clotted,
  insufficient-volume, mislabeled). Reference: CLSI GP26.
* ``HEMOLYSIS_RATE`` (0.03, 3%) — approximates the published aggregate
  hemolysis rate for phlebotomy on non-hemolysis-prone analytes; K/LDH
  are treated as the JCCLS-flagged prone pair. Reference: Lippi et al.,
  hemolysis QI literature.
* ``HEMOLYSIS_LIFT_RANGE`` — potassium (K) and LDH lift bounds when the
  sample is hemolysed. 1.2-1.8× true value approximates the range
  clinicians see and mirrors the corresponding UI flag ``H*`` in
  ``OrderResult``.
* ``HEMOLYSIS_PRONE_LABS`` — the two-analyte set (K, LDH) that JCCLS
  material-artefact tables flag as sensitive to hemolysis. The set is
  intentionally minimal; extending it requires an evidence-based rationale
  per analyte.
"""

from __future__ import annotations

SPECIMEN_REJECTION_RATE: float = 0.02
"""Per-order probability of specimen rejection (CANCELLED order status)."""

HEMOLYSIS_RATE: float = 0.03
"""Per-order probability of hemolysis when the analyte is in
``HEMOLYSIS_PRONE_LABS``. Non-prone analytes are never hemolysed."""

HEMOLYSIS_LIFT_RANGE: tuple[float, float] = (1.2, 1.8)
"""(low, high) multiplier applied to the true value when hemolysed —
uniform-sampled per hemolysed order."""

HEMOLYSIS_PRONE_LABS: frozenset[str] = frozenset({"K", "LDH"})
"""Analytes flagged as hemolysis-prone (JCCLS material-artefact table).
Adding a new analyte requires per-analyte evidence."""
