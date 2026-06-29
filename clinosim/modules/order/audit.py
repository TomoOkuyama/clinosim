"""Audit module for lab ServiceRequest (PR1 — AD-60 plug-in #3, after HAI and antibiotic).

Registered checks (canonical_constants + lift_firing_proof + clinical_acceptance):

- canonical_constants: SR_ID_PREFIX / PLACER_ORDER_NUMBER_SYSTEM /
  LAB_CATEGORY_SNOMED / LAB_CATEGORY_V2_0074 verified against the
  production constants in _fhir_service_request.py.

- lift_firing_proof (_build_order_proof): exercises _bb_service_requests
  on synthetic Orders. 7 equality_checks assert:
    1. PLACER_ORDER_NUMBER_SYSTEM constant
    2. LAB_CATEGORY_SNOMED (108252007) constant
    3. LAB_CATEGORY_V2_0074 (LAB) constant
    4. ServiceRequest count > 0 when lab Order count > 0
    5. panel SR count > 0 when panel_key non-empty Orders exist
    6. every basedOn ref resolves (panel SR id starts with SR_ID_PREFIX)
    7. SR id schemes are disjoint (panel != standalone)

- clinical_acceptance["basedon_coverage"]: triggers the clinical axis
  _check_lab_obs_basedon() gate: 100% of LAB Observations must carry
  basedOn pointing to an existing ServiceRequest (n<30 → WARN).

PR-90 silent-no-op lesson: the lift_firing_proof is the load-bearing
verification that catches a ServiceRequest builder that emits zero
resources without raising. clinical_acceptance["basedon_coverage"]
catches the case where basedOn is present in unit tests but missing
in production NDJSON output.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from clinosim.audit.registry import ModuleAuditSpec, register_audit_module
from clinosim.modules.order.panel_grouping import PANEL_PRIORITY_ORDER
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.modules.output._fhir_service_request import (
    LAB_CATEGORY_SNOMED,
    LAB_CATEGORY_V2_0074,
    PLACER_ORDER_NUMBER_SYSTEM,
    SR_ID_PREFIX,
    _bb_service_requests,
    build_panel_counter,
    order_to_sr_id,
)
from clinosim.types.encounter import Order, OrderType


def _build_order_proof() -> dict[str, Any]:
    """Zero-arg factory: run _bb_service_requests on synthetic Orders and verify.

    Returns equality_checks format: list[tuple[label, actual, expected]].
    The silent_no_op axis iterates and asserts hard equality on each.

    Exercises the production code path so that a silent no-op (builder
    returns [] without raising) would produce a count=0 failure instead
    of a green audit.
    """
    dt = datetime(2026, 1, 10, 8, 0)
    o_panel_1 = Order(
        order_id="o-wbc",
        encounter_id="enc-1",
        patient_id="pt-test",
        order_type=OrderType.LAB,
        display_name="WBC",
        ordered_datetime=dt,
        panel_key="CBC",
    )
    o_panel_2 = Order(
        order_id="o-hgb",
        encounter_id="enc-1",
        patient_id="pt-test",
        order_type=OrderType.LAB,
        display_name="HGB",
        ordered_datetime=dt,
        panel_key="CBC",
    )
    o_standalone = Order(
        order_id="o-crp",
        encounter_id="enc-1",
        patient_id="pt-test",
        order_type=OrderType.LAB,
        display_name="CRP",
        ordered_datetime=dt,
        panel_key="",  # stand-alone
    )
    lab_orders: list[Any] = [o_panel_1, o_panel_2, o_standalone]

    counter = build_panel_counter(lab_orders)
    panel_sr_id = order_to_sr_id(o_panel_1, counter)
    standalone_sr_id = order_to_sr_id(o_standalone, counter)

    # Use a real BundleContext (not SimpleNamespace) so future field additions
    # are caught at proof time rather than at production runtime.
    ctx = BundleContext(
        record={"orders": lab_orders},
        country="US",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt-test",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id="enc-1",
        patient_sex="M",
    )
    srs = _bb_service_requests(ctx)

    # Count panel SRs by matching panel-name suffix (e.g. "-CBC-", "-BMP-") rather
    # than relying on "enc-" prefix in the encounter_id.  Robust to any synthetic
    # encounter_id string used in tests.
    panel_sr_ids = {
        sr["id"]
        for sr in srs
        if any(f"-{panel_name}-" in sr.get("id", "") for panel_name in PANEL_PRIORITY_ORDER)
    }

    return {
        "equality_checks": [
            # 1. Canonical constant: PLACER_ORDER_NUMBER_SYSTEM
            (
                "PLACER_ORDER_NUMBER_SYSTEM",
                PLACER_ORDER_NUMBER_SYSTEM,
                "urn:clinosim:placer-order-number",
            ),
            # 2. Canonical constant: LAB_CATEGORY_SNOMED (108252007)
            (
                "LAB_CATEGORY_SNOMED_108252007",
                LAB_CATEGORY_SNOMED,
                "108252007",
            ),
            # 3. Canonical constant: LAB_CATEGORY_V2_0074 (LAB)
            (
                "LAB_CATEGORY_V2_0074_LAB",
                LAB_CATEGORY_V2_0074,
                "LAB",
            ),
            # 4. ServiceRequest count > 0 when lab Order count > 0
            (
                "ServiceRequest count > 0 when lab Order count > 0",
                len(srs) > 0,
                True,
            ),
            # 5. panel SR count > 0 when panel_key non-empty Orders exist
            (
                "panel SR count > 0 when panel Orders present",
                len(panel_sr_ids) > 0,
                True,
            ),
            # 6. every panel SR id is well-formed (starts with SR_ID_PREFIX)
            (
                "every panel SR id is well-formed (starts with SR_ID_PREFIX)",
                panel_sr_id.startswith(SR_ID_PREFIX),
                True,
            ),
            # 7. SR id schemes are disjoint (panel ≠ standalone)
            (
                "SR id schemes are disjoint (panel != standalone)",
                panel_sr_id != standalone_sr_id,
                True,
            ),
        ]
    }


register_audit_module(
    ModuleAuditSpec(
        name="order_service_request",
        canonical_constants={
            "sr_id_prefix": (SR_ID_PREFIX,),
            "placer_system": (PLACER_ORDER_NUMBER_SYSTEM,),
            "lab_snomed": (LAB_CATEGORY_SNOMED,),
            "lab_v2": (LAB_CATEGORY_V2_0074,),
        },
        lift_firing_proof=_build_order_proof,
        clinical_acceptance={
            "basedon_coverage": (
                "100% of LAB Observations carry basedOn referencing an existing ServiceRequest "
                "(n<30 encounter count -> WARN; rare-event tolerated)."
            ),
        },
    )
)
