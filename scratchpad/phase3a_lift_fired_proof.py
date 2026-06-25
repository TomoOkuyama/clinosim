"""Proves apply_hai_lab_lift actually mutates WBC + CRP values in the
post-PR-90 fix path. Compares two hand-built records (one with a synthetic
HAI event, one without) and asserts the lifted values differ by exactly
the closed-form delta.

This is the proof that survived the post-PR-90 xhigh review: the lift is
mathematically firing for any record whose extensions["hai"] has canonical
lowercase hai_type strings (the YAML loader now validates this at import).
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.hai import HAI_TYPES
from clinosim.modules.hai.lab_lift import _hai_lift_delta, apply_hai_lab_lift
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Order, OrderResult, OrderType
from clinosim.types.hai import HAIEvent


def main() -> None:
    print(f"HAI_TYPES canonical: {HAI_TYPES}")

    state = PhysiologicalState(inflammation_level=0.4)
    history = [state, state, state, state, state, state, state]
    admission = datetime(2026, 1, 8, 0)

    # Build identical records, then add a CAUTI HAIEvent to one
    wbc_seed = 11760.0  # baseline at infl=0.4, hour=6
    crp_seed = 25.9

    obs_dt = datetime(2026, 1, 12, 8)  # day 4 = onset+2 if onset = day 2
    wbc_obs_base = OrderResult(
        result_datetime=obs_dt, lab_name="WBC", value=wbc_seed,
    )
    crp_obs_base = OrderResult(
        result_datetime=obs_dt, lab_name="CRP", value=crp_seed,
    )
    wbc_order = Order(
        order_id="o-wbc", order_type=OrderType.LAB, display_name="WBC",
        ordered_datetime=datetime(2026, 1, 12, 6, 30),
    )
    wbc_order.result = wbc_obs_base
    crp_order = Order(
        order_id="o-crp", order_type=OrderType.LAB, display_name="CRP",
        ordered_datetime=datetime(2026, 1, 12, 6, 30),
    )
    crp_order.result = crp_obs_base

    # Baseline (no HAI): extensions empty
    rec_baseline = SimpleNamespace(
        patient=SimpleNamespace(sex="M"),
        extensions={},
        lab_results=[wbc_obs_base, crp_obs_base],
        orders=[wbc_order, crp_order],
    )
    encounter = SimpleNamespace(encounter_id="enc-1")
    n_base = apply_hai_lab_lift(rec_baseline, encounter, history, admission)
    base_wbc, base_crp = wbc_obs_base.value, crp_obs_base.value
    print(f"\nBaseline (no HAI):  modifications={n_base}, WBC={base_wbc}, CRP={base_crp}")
    assert n_base == 0

    # Lifted: synthetic CAUTI event
    wbc_obs2 = OrderResult(
        result_datetime=obs_dt, lab_name="WBC", value=wbc_seed,
    )
    crp_obs2 = OrderResult(
        result_datetime=obs_dt, lab_name="CRP", value=crp_seed,
    )
    wbc_o2 = deepcopy(wbc_order)
    wbc_o2.result = wbc_obs2
    crp_o2 = deepcopy(crp_order)
    crp_o2.result = crp_obs2

    rec_lifted = SimpleNamespace(
        patient=SimpleNamespace(sex="M"),
        extensions={"hai": [
            HAIEvent(
                hai_id="h1", encounter_id="enc-1", hai_type="cauti",
                source_device_id="d1", icd10_code="T83.511A",
                snomed_code="68566005", onset_date="2026-01-10",
                organism_snomed="112283007", culture_specimen_id="s1",
            ),
        ]},
        lab_results=[wbc_obs2, crp_obs2],
        orders=[wbc_o2, crp_o2],
    )
    n_lift = apply_hai_lab_lift(rec_lifted, encounter, history, admission)
    new_wbc, new_crp = wbc_obs2.value, crp_obs2.value

    # Closed-form expected delta
    expected_wbc_delta = _hai_lift_delta(state, "WBC", 0.20, draw_hour=6)
    expected_crp_delta = _hai_lift_delta(state, "CRP", 0.20, draw_hour=6)

    print(f"With CAUTI HAI:     modifications={n_lift}, WBC={new_wbc}, CRP={new_crp}")
    print(f"Closed-form delta:  WBC+{expected_wbc_delta:.0f}, CRP+{expected_crp_delta:.1f}")
    print(f"Observed delta:     WBC+{new_wbc - base_wbc:+.0f}, CRP+{new_crp - base_crp:+.1f}")

    assert n_lift == 2, "lift should modify 2 obs (WBC + CRP)"
    assert abs(new_wbc - base_wbc - expected_wbc_delta) < 1.5, (
        f"WBC delta {new_wbc - base_wbc} ≠ expected {expected_wbc_delta}"
    )
    assert abs(new_crp - base_crp - expected_crp_delta) < 0.5, (
        f"CRP delta {new_crp - base_crp} ≠ expected {expected_crp_delta}"
    )
    print("\n✅ PROOF: apply_hai_lab_lift fires and produces the closed-form delta.")
    print("         The PR-90 case-mismatch bug is fixed and the lift code is live.")


if __name__ == "__main__":
    main()
