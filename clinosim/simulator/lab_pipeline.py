"""Lab-result generation pipeline (Issue #552 PR A).

Extracted from ``_run_daily_loop`` in ``clinosim/simulator/inpatient.py`` —
the two-pass lab-result generation (~117 LOC in the caller) that turns
placed lab orders into ``OrderResult`` records with per-analyte
noise / hemolysis / specimen-rejection modeling.

Pass 1 — scalar + non-panel orders. Each order is one specimen, so its
own ``individual_lab_seed`` sub-RNG is drawn (AD-16). Pre-analytical
issues fire per order.

Pass 2 — panel children. A panel is ONE specimen, so specimen rejection
fires at most once per parent and cancels every child. Per-child
hemolysis is still drawn per child from the parent's sub-RNG stream.

RNG contract (byte-neutral extraction, spec):
  * NO master-RNG consumption inside this pipeline. Every draw comes
    from a per-specimen sub-RNG (``individual_lab_seed`` for scalar
    orders, ``panel_specimen_seed`` for panel parents).
  * Pass 1 runs before Pass 2 (exact iteration order preserved).

The pipeline MUTATES ``orders`` in place (assigning ``order.result`` /
``order.status``) and APPENDS the produced ``OrderResult`` records to a
returned list. Callers extend their own ``all_lab_results`` list from
that return value.

Byte-neutral verification: pre-extraction and post-extraction 30-patient
seed 42 JP+US cohorts must diff at zero non-timestamp lines.
"""

from __future__ import annotations

from typing import Any

from clinosim import determinism
from clinosim.modules.observation.engine import (
    canonical_lab_name,
    clamp_to_physiologic_limits,
    determine_flag,
    generate_lab_result,
    get_lab_unit,
)
from clinosim.modules.observation.pre_analytical import (
    HEMOLYSIS_LIFT_RANGE,
    HEMOLYSIS_PRONE_LABS,
    HEMOLYSIS_RATE,
    SPECIMEN_REJECTION_RATE,
)
from clinosim.modules.order.engine import calculate_result_time_from_state
from clinosim.modules.staff.engine import FALLBACK_TECH_ID, StaffRoster, assign_staff
from clinosim.seeding import individual_lab_seed, panel_specimen_seed
from clinosim.types.encounter import Order, OrderResult, OrderStatus
from clinosim.types.patient import PatientProfile


def _run_lab_result_pipeline(
    all_orders: list[Order],
    panel_children_by_parent: dict[str, list[Order]],
    panel_child_ids: set[str],
    true_labs: dict[str, float],
    patient: PatientProfile,
    country_key: str,
    roster: StaffRoster,
    hospital_state: Any,
    hospital_ops: dict | None,
) -> list[OrderResult]:
    """Run Pass 1 (scalar / non-panel orders) + Pass 2 (panel children) and
    return the ``OrderResult`` records produced.

    Mutates:
      * ``all_orders[i].status`` / ``all_orders[i].result`` for lab orders.
      * ``panel_children_by_parent[parent_id][i].status`` /
        ``.result`` for panel children.

    Returns:
      Flat list of ``OrderResult`` records, in the exact order they were
      produced by the two passes. Caller extends its own ``all_lab_results``
      list from this return value so downstream serialisers see the same
      order they did before the extraction.
    """
    produced: list[OrderResult] = []

    # === Pass 1: scalar + non-panel orders, drawn from a per-order isolated
    # sub-RNG (individual_lab_seed). This mirrors the panel-children Pass 2
    # design: each individual lab order is one specimen, so specimen
    # rejection, hemolysis, technician assignment, and noise must come from
    # an isolated stream so YAML edits that flip a {test:"X"} order from
    # "engine doesn't produce X" to "engine produces X" (e.g. Cl/Ca after
    # derive_lab_values is extended) cannot shuffle unrelated patients'
    # cohorts via the master stream (AD-16). Panel children are skipped
    # here; they are resulted in Pass 2 against panel_specimen_seed.
    for order in all_orders:
        if order.order_id in panel_child_ids:
            continue
        canon = canonical_lab_name(order.display_name)
        if order.order_type.value == "lab" and order.status == OrderStatus.PLACED and canon in true_labs:
            lab_rng = determinism.default_rng(individual_lab_seed(order.order_id))
            # Pre-analytical issues (constants in observation/pre_analytical.py):
            # ~2% specimen rejection, ~3% hemolysis on K/LDH.
            if lab_rng.random() < SPECIMEN_REJECTION_RATE:
                order.status = OrderStatus.CANCELLED
                continue  # specimen lost/rejected
            if canon in HEMOLYSIS_PRONE_LABS and lab_rng.random() < HEMOLYSIS_RATE:
                # Hemolyzed sample → falsely elevated K/LDH, flagged.
                # Issue #735: clamp to PHYSIOLOGIC_LIMITS so the falsely-lifted
                # value stays within a survivable band (e.g. K ≤ 8.5 mmol/L,
                # matching real clinical lab behavior of rejecting samples that
                # would report life-incompatible K).
                result_time = calculate_result_time_from_state(order, hospital_state, hospital_ops or {}, lab_rng)
                hemolyzed_val = true_labs[canon] * float(lab_rng.uniform(*HEMOLYSIS_LIFT_RANGE))
                hemolyzed_val = clamp_to_physiologic_limits(canon, hemolyzed_val)
                lab_tech = assign_staff("lab_result", "", roster, lab_rng).get(
                    "performing_technician", FALLBACK_TECH_ID
                )
                order.result = OrderResult(
                    result_datetime=result_time,
                    performed_by=lab_tech,
                    lab_name=canon,
                    value=round(hemolyzed_val, 1),
                    unit=get_lab_unit(canon),
                    flag="H*",
                )
                order.status = OrderStatus.RESULTED
                produced.append(order.result)
                continue

            result_time = calculate_result_time_from_state(order, hospital_state, hospital_ops or {}, lab_rng)
            observed = generate_lab_result(canon, true_labs[canon], lab_rng)
            flag = determine_flag(canon, observed, sex=patient.sex, country="JP" if country_key == "japan" else "US")
            lab_tech = assign_staff("lab_result", "", roster, lab_rng).get("performing_technician", FALLBACK_TECH_ID)
            order.result = OrderResult(
                result_datetime=result_time,
                performed_by=lab_tech,
                lab_name=canon,
                value=observed,
                unit=get_lab_unit(canon),
                flag=flag,
            )
            order.status = OrderStatus.RESULTED
            produced.append(order.result)

    # === Pass 2: panel children, one isolated sub-RNG per parent specimen.
    # Clinical model: a panel order is **one specimen**, so specimen-rejection
    # fires at most once per parent and cancels every child of that parent.
    # Per-analyte hemolysis is drawn after specimen acceptance. Components not
    # present in true_labs (e.g. BMP Cl/Ca until derive_lab_values produces them)
    # are silently skipped — the child stays PLACED with no result, matching
    # the existing behaviour for any individual order that engine cannot result.
    for parent_id, children in panel_children_by_parent.items():
        sub_rng = determinism.default_rng(panel_specimen_seed(parent_id))
        if sub_rng.random() < SPECIMEN_REJECTION_RATE:
            for child in children:
                child.status = OrderStatus.CANCELLED
            continue
        for child in children:
            canon = canonical_lab_name(child.display_name)
            if canon not in true_labs:
                continue  # silently dropped; status stays PLACED
            result_time = calculate_result_time_from_state(
                child,
                hospital_state,
                hospital_ops or {},
                sub_rng,
            )
            lab_tech = assign_staff(
                "lab_result",
                "",
                roster,
                sub_rng,
            ).get("performing_technician", FALLBACK_TECH_ID)
            if canon in HEMOLYSIS_PRONE_LABS and sub_rng.random() < HEMOLYSIS_RATE:
                # Issue #735: same PHYSIOLOGIC_LIMITS clamp as Pass 1 above.
                hemolyzed_val = true_labs[canon] * float(sub_rng.uniform(*HEMOLYSIS_LIFT_RANGE))
                hemolyzed_val = clamp_to_physiologic_limits(canon, hemolyzed_val)
                child.result = OrderResult(
                    result_datetime=result_time,
                    performed_by=lab_tech,
                    lab_name=canon,
                    value=round(hemolyzed_val, 1),
                    unit=get_lab_unit(canon),
                    flag="H*",
                )
            else:
                observed = generate_lab_result(canon, true_labs[canon], sub_rng)
                flag = determine_flag(
                    canon, observed, sex=patient.sex, country="JP" if country_key == "japan" else "US"
                )
                child.result = OrderResult(
                    result_datetime=result_time,
                    performed_by=lab_tech,
                    lab_name=canon,
                    value=observed,
                    unit=get_lab_unit(canon),
                    flag=flag,
                )
            child.status = OrderStatus.RESULTED
            produced.append(child.result)

    return produced
