"""clinosim.modules.resuscitation — the resuscitation attempt of a full-code in-hospital death (Issue #3483).

A deceased inpatient / emergency record whose code status is the full-code
tier gets a CPR procedure ending at the death time and the epinephrine doses
given during it. Registered as POST_RECORDS order 55, right after
``code_status`` (50), whose tier it reads.

See ``clinosim/modules/resuscitation/README.md`` (canonical 11-section) for
design + spec.
"""

from clinosim.modules.resuscitation.engine import (
    build_cpr_procedure,
    build_epinephrine,
    is_resuscitation_order,
    load_rules,
)

__all__ = [
    "build_cpr_procedure",
    "build_epinephrine",
    "is_resuscitation_order",
    "load_rules",
]
