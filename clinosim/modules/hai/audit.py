"""HAI audit — first per-Module audit plug-in.

Absorbs scratchpad/phase3a_lift_fired_proof.py: builds a synthetic
record with a CAUTI HAIEvent at baseline infl=0.4, draw_hour=6,
calls apply_hai_lab_lift, and asserts the observed delta matches the
closed-form _hai_lift_delta — the load-bearing verification PR-90 was
missing.

Registered checks:
- canonical_constants: HAI_TYPES against
  modules/hai/reference_data/hai_lab_lift.yaml hai_lift section
- structural_obs_codes: WBC (LOINC 6690-2 + JLAC10 2A010), CRP
  (LOINC 1988-5 + JLAC10 5C070)
- clinical_acceptance: CAUTI (WBC delta ≥ 1500, CRP delta ≥ 25),
  CLABSI / VAP (each ≥ 3000 / ≥ 50) — small cohorts → WARN
- lift_firing_proof: synthetic CAUTI record returns the same
  closed-form delta apply_hai_lab_lift produces
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.hai import HAI_TYPES
from clinosim.modules.hai.lab_lift import _hai_lift_delta, apply_hai_lab_lift
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Order, OrderResult, OrderType
from clinosim.types.hai import HAIEvent

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_HAI_LIFT_YAML = _REF_DIR / "hai_lab_lift.yaml"


def _build_cauti_proof():
    state = PhysiologicalState(inflammation_level=0.4)
    # state_history layout: index 0 = admission state, index N+1 = post-day-N
    history = [state for _ in range(7)]
    admission = datetime(2026, 1, 8, 0)
    obs_dt = datetime(2026, 1, 12, 8)
    draw_hour = 6

    wbc_obs = OrderResult(
        result_datetime=obs_dt,
        lab_name="WBC",
        value=11760.0,
    )
    wbc_order = Order(
        order_id="o-wbc",
        order_type=OrderType.LAB,
        display_name="WBC",
        ordered_datetime=datetime(2026, 1, 12, draw_hour, 30),
    )
    wbc_order.result = wbc_obs

    record = SimpleNamespace(
        patient=SimpleNamespace(sex="M"),
        extensions={
            "hai": [
                HAIEvent(
                    hai_id="h-cauti-1",
                    encounter_id="enc-1",
                    hai_type=HAI_TYPES[1],
                    source_device_id="d1",
                    icd10_code="T83.511A",
                    snomed_code="68566005",
                    onset_date="2026-01-10",
                    organism_snomed="112283007",
                    culture_specimen_id="s1",
                )
            ]
        },
        lab_results=[wbc_obs],
        orders=[wbc_order],
    )
    encounter = SimpleNamespace(encounter_id="enc-1")
    expected_wbc_delta = _hai_lift_delta(state, "WBC", 0.20, draw_hour=draw_hour)
    pre_value = wbc_obs.value

    return {
        "record": record,
        "encounter": encounter,
        "state_history": history,
        "admission_time": admission,
        "apply_fn": apply_hai_lab_lift,
        "expected": [(wbc_obs, pre_value, expected_wbc_delta)],
    }


register_audit_module(
    ModuleAuditSpec(
        name="hai",
        canonical_constants={"hai_type": HAI_TYPES},
        yaml_keys_to_validate={
            str(_HAI_LIFT_YAML): ("hai_lift",),
        },
        structural_obs_codes={
            "WBC": ("6690-2", "2A010"),
            "CRP": ("1988-5", "5C070"),
        },
        clinical_acceptance={
            "cauti": {
                "icd10_code": "T83.511A",
                "WBC_delta_p50": 1500,
                "CRP_delta_p50": 25,
            },
            "clabsi": {
                "icd10_code": "T80.211A",
                "WBC_delta_p50": 3000,
                "CRP_delta_p50": 50,
            },
            "vap": {
                "icd10_code": "J95.851",
                "WBC_delta_p50": 3000,
                "CRP_delta_p50": 50,
            },
        },
        lift_firing_proof=_build_cauti_proof,
    )
)
