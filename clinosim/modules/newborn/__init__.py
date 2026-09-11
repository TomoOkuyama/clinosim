"""clinosim.modules.newborn — birth-admission clinical workup.

Emits the clinical events every real neonatal chart carries during the
birth admission that no other module owns:

* Vitamin K prophylaxis — this PR's slice.
* Apgar score at 1 min / 5 min — reserved for follow-up (#1252 N4).
* AABR hearing screen — reserved (#1252 N5).
* Tandem-MS metabolic mass screen — reserved (#1252 N6).
* Bilirubin monitoring / CCHD SpO2 screen / ophthalmic prophylaxis —
  reserved (#1252 N7).

Firing gate: `condition_event.condition_type == "newborn_birth"`,
stamped by `simulator/perinatal.py` on the baby-side CIF record. Non-
newborn records are a no-op.

Registered as POST_ENCOUNTER order 92 — after every encounter-level
enricher populates its own data and before the document enricher (95)
that may reference newborn events in narrative sections.

Design context: this module was carved out under Issue #1252 rather
than folded into `simulator/perinatal.py` (which stays focused on
Encounter + Patient shells) or `modules/pediatric/` (post-discharge
scope). See the #1252 issue comment for the module-boundary rationale.
"""

from clinosim.modules.newborn.engine import (
    build_apgar_scores,
    build_newborn_shift_vitals,
    build_vitamin_k_administrations,
    is_newborn_birth_record,
    load_newborn_config,
)
from clinosim.modules.newborn.enricher import enrich_newborn

__all__ = [
    "build_apgar_scores",
    "build_newborn_shift_vitals",
    "build_vitamin_k_administrations",
    "enrich_newborn",
    "is_newborn_birth_record",
    "load_newborn_config",
]
