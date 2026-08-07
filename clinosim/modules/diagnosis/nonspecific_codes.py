"""Named constants for non-specific / fallback ICD-10 codes used across the simulator.

Previously scattered as bare string literals in `inpatient.py` / `outpatient.py` /
`emergency.py` / `diagnosis/engine.py`. Two problems that caused:

* `inpatient.py:418` used ``"R05"`` (a real code for Cough) as a
  ``diagnosis_correct`` sentinel — legitimate cough presentations were silently
  marked incorrect. The engine's actual unresolved-diagnosis sentinel is
  ``"R69"``, so the two disagreed and neither location was named.
* Bare literals meant a rename or clinical review had to grep across modules.

Names below quote the ICD-10 title verbatim so a rename triggers an
ImportError rather than silent drift.

Issue #551 lands the first two constants (``UNRESOLVED_DIAGNOSIS_ICD`` and
``ICD_COUGH`` — the code that used to double as the wrong-dx sentinel). The
remaining fallback codes (``R50.9`` / ``R53.1`` / ``R68.8`` / ``Z09``) are
tracked in the follow-up issue that will extract them in one sweep.
"""

from __future__ import annotations

# The engine's "differential did not converge" fallback. Returned by
# `clinosim.modules.diagnosis.engine._pick_discharge_dx` when no working
# diagnosis and no candidate can be resolved. When a downstream builder sees
# this value as the discharge code, the diagnosis was NOT correctly identified.
UNRESOLVED_DIAGNOSIS_ICD = "R69"

# ICD-10 R05 = "Cough" — a real clinical code. Historically also (mis)used
# in `inpatient.py` as a wrong-dx sentinel; that usage is removed as of
# Issue #551. Exported here so any future dedup / display work can reference
# the same string without re-introducing a literal.
ICD_COUGH = "R05"
