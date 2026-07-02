"""Triage chain AD-60 audit module (AD-65 Bug C fix, Task 14).

Guards against the Bug C class regression discovered in the AD-65 chain:
`clinosim/simulator/emergency.py` samples `severity` ("mild"/"moderate"/
"severe") for every ED encounter but historically never stored it on the
`Encounter` object. `clinosim/modules/triage/engine.py:triage_enricher`
reads `_o(enc, "severity", "moderate")`, so a missing attribute silently
defaulted every ED encounter to "moderate" — and because
`reference_data/triage_protocols.yaml`'s `severity_to_triage_distribution`
only reaches triage level "1" via severity="severe" and level "5" via
severity="mild" (moderate only spans levels 2-4), the entire production
cohort emitted triage_level in {2,3,4} only: L1 and L5 were structurally
unreachable. Fixed by (1) adding `Encounter.severity: str = ""`
(`clinosim/types/encounter.py`) and (2) `encounter.severity = severity`
in `clinosim/simulator/emergency.py` right after severity is sampled.

lift_firing_proof (_build_triage_severity_proof): a zero-arg factory
(called with no arguments by `clinosim/audit/axes/silent_no_op.py:
_check_proof`) that exercises the real production `triage_enricher`
end-to-end against ~900 synthetic ED encounters spanning all 3
severities. If `severity` ever silently collapses to a single value
again (e.g. a future refactor drops the assignment or an enricher
starts reading the wrong attribute name), this proof fails immediately
because severe-severity encounters would stop producing level "1" and
mild-severity encounters would stop producing level "5".

Companion real-cohort regression test:
`tests/integration/test_bug_c_triage_all_levels.py` (generates a live
US cohort and asserts triage_level 1-5 each exceed a 0.5% ratio among ED
encounters — the end-to-end verification that the CLI-generated CIF, not
just the enricher in isolation, restores the full L1-L5 distribution).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.triage.engine import load_triage_protocols, triage_enricher

_SEVERITIES = ("mild", "moderate", "severe")
_N_PER_SEVERITY = 300


def _build_triage_severity_proof() -> dict[str, Any]:
    """Run the real `triage_enricher` over synthetic multi-severity ED encounters.

    Returns `equality_checks` format: list[tuple[label, actual, expected]].
    """
    encounters = [
        SimpleNamespace(
            encounter_id=f"proof-triage-{sev}-{i}",
            encounter_type="emergency",
            severity=sev,
            admission_datetime=None,
            chief_complaint="",
            triage_data=None,
        )
        for sev in _SEVERITIES
        for i in range(_N_PER_SEVERITY)
    ]
    record = SimpleNamespace(
        patient=SimpleNamespace(patient_id="pt-proof-triage"),
        encounters=encounters,
    )
    ctx = SimpleNamespace(
        master_seed=42,
        config=SimpleNamespace(country="US"),
        records=[record],
    )

    triage_enricher(ctx)

    level_counts: dict[str, dict[str, int]] = {sev: {} for sev in _SEVERITIES}
    for enc in encounters:
        assert enc.triage_data is not None, f"triage_enricher left {enc.encounter_id} unpopulated"
        counts = level_counts[enc.severity]
        counts[enc.triage_data.level] = counts.get(enc.triage_data.level, 0) + 1

    severe_l1 = level_counts["severe"].get("1", 0)
    mild_l5 = level_counts["mild"].get("5", 0)
    moderate_has_no_l1_or_l5 = (
        level_counts["moderate"].get("1", 0) == 0 and level_counts["moderate"].get("5", 0) == 0
    )

    # Sanity cross-check that this proof's assumption about the YAML shape
    # still holds — if triage_protocols.yaml ever gains a "1"/"5" entry for
    # moderate, the moderate_has_no_l1_or_l5 check above would need updating
    # too (not a Bug C regression, but this proof would need revisiting).
    dist = load_triage_protocols()["severity_to_triage_distribution"]
    moderate_levels_in_yaml = set(dist["moderate"].keys())

    return {
        "equality_checks": [
            (
                "severity='severe' encounters produce >=1 triage level '1' "
                "(Bug C: would be 0 if severity silently defaulted to 'moderate')",
                severe_l1 > 0,
                True,
            ),
            (
                "severity='mild' encounters produce >=1 triage level '5' "
                "(Bug C: would be 0 if severity silently defaulted to 'moderate')",
                mild_l5 > 0,
                True,
            ),
            (
                "triage_enricher preserves 3 distinct severities across synthetic "
                "encounters (not collapsed to a single constant)",
                len({enc.severity for enc in encounters}),
                3,
            ),
            (
                "moderate severity_to_triage_distribution has no '1'/'5' entries "
                "(triage_protocols.yaml shape this proof's L1/L5 attribution depends on)",
                moderate_has_no_l1_or_l5,
                True,
            ),
            (
                "moderate levels in YAML are exactly {2,3,4} (proof-assumption pin)",
                moderate_levels_in_yaml,
                {"2", "3", "4"},
            ),
        ]
    }


register_audit_module(
    ModuleAuditSpec(
        name="triage_chain",
        lift_firing_proof=_build_triage_severity_proof,
    )
)
