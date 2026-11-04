"""Canonical acuity-tier disease sets (Issue #563).

Two overlapping sets used to be inlined as ad-hoc tuples across
`simulator/inpatient.py`. They encode related but distinct clinical
routing:

* **EMERGENCY_PRIORITY_DISEASES** — `Encounter.priority = "EM"`
* **CRITICAL_MONITORING_DISEASES** — q1-2h vital-sign sampling

The neurosurgical-emergency invasive-line rule (hemorrhagic stroke,
subdural hematoma) is a row of `procedure/reference_data/procedure_rules.yaml`
(Issue #2525).

Inlining them meant the priority code and the vitals frequency could drift
silently. Issue #563 uncovered exactly
that drift: ``subdural_hematoma`` was in EMERGENCY_PRIORITY but missing
from CRITICAL_MONITORING — a subdural-hematoma admission carried
``priority=EM`` yet was sampled q4h instead of q1-2h.

Presence of a disease id in these sets is a load-bearing clinical fact;
adding or removing an entry is a data-quality PR, not a refactor.

The neuro-perfusion set (`_NEURO_DISEASES` in `vitals_pipeline.py`) is a
different concept (perfusion-based LOC assessment across 6 diseases).
"""

from __future__ import annotations

EMERGENCY_PRIORITY_DISEASES: frozenset[str] = frozenset(
    {
        "acute_mi",
        "sepsis",
        "hemorrhagic_stroke",
        "subdural_hematoma",
        "traffic_accident_severe",
    }
)
"""Diseases mapping to ``Encounter.priority = 'EM'`` in the inpatient path.

Consumers: ``clinosim/simulator/inpatient.py::_finalize_encounter`` (line
around 487). Adding a disease here also warrants review of
``CRITICAL_MONITORING_DISEASES`` — the two sets almost always move together.
"""

CRITICAL_MONITORING_DISEASES: frozenset[str] = frozenset(
    {
        "acute_mi",
        "sepsis",
        "hemorrhagic_stroke",
        "subdural_hematoma",
        "traffic_accident_severe",
    }
)
"""Diseases triggering q1-2h vital signs (versus q4h for unstable-but-not-
critical, q6h routine).

Consumers: ``clinosim/simulator/inpatient.py::_generate_vitals`` (line
around 1938). Sibling of ``EMERGENCY_PRIORITY_DISEASES``; historically
these two sets drifted (``subdural_hematoma`` was in one but not the
other — Issue #563 aligned them).
"""
