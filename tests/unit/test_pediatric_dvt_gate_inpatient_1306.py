"""Issue #1306 — pediatric Enoxaparin leak on the inpatient
DVT-prophylaxis path (post-#1276 regression).

PR #1276 gated the enricher-side ``build_dvt_prophylaxis_orders`` on
patient age < 15, but the disease-YAML supportive-orders fallback in
``modules/order/engine.place_admission_orders`` still emitted a
``DVT_prophylaxis: Enoxaparin`` Order regardless of age. Exemplar
inpatient encounters at p=10k s355 US: 4 patients aged 3 / 6 / 8 / 14
(all J13 / J12.9 pneumonia) received Enoxaparin.

Fix threads ``patient_age`` into ``place_admission_orders`` and strips
any ``DVT_prophylaxis`` entry from the supportive list when the patient
is younger than the ceiling declared in ``prophylaxis_rules.yaml``.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from clinosim.modules.order.engine import place_admission_orders


def _protocol_with_fallback_supportive() -> dict:
    """A minimal protocol dict where the disease YAML does NOT declare
    ``order_protocols.admission_orders.supportive`` — the caller falls
    back to the hard-coded default that includes DVT_prophylaxis.
    """
    return {
        "order_protocols": {"admission_orders": {"labs": []}},
        "expected_lab_distributions": {"admission": {}},
    }


def _protocol_with_yaml_dvt_prophylaxis() -> dict:
    """A protocol whose YAML explicitly declares DVT_prophylaxis in
    ``supportive`` (yaml-driven emit path — the pediatric gate must
    strip this too, not just the fallback path)."""
    return {
        "order_protocols": {
            "admission_orders": {
                "labs": [],
                "supportive": [
                    {"type": "IV_fluid", "detail": "NS 100 mL/h"},
                    {"type": "DVT_prophylaxis", "detail": "Enoxaparin 40mg SC daily"},
                    {"type": "Positioning", "detail": "HOB 30 degrees"},
                ],
            }
        },
        "expected_lab_distributions": {"admission": {}},
    }


def _run(protocol: dict, age: int | None) -> list:
    rng = np.random.default_rng(42)
    return place_admission_orders(
        protocol,
        "pt-test",
        "enc-test",
        datetime(2026, 5, 1, 9, 0, 0),
        country="US",
        rng=rng,
        patient_age=age,
    )


def _has_enoxaparin(orders) -> bool:
    return any("Enoxaparin" in (o.display_name or "") for o in orders)


def _has_iv_fluid(orders) -> bool:
    return any((o.display_name or "").startswith("IV_fluid:") for o in orders)


def test_no_patient_gets_enoxaparin_from_place_admission_orders_after_1342():
    """Issue #1342: after unifying DVT_prophylaxis emit through the
    ``prophylaxis.enricher`` single-source path, ``place_admission_orders``
    NEVER emits an Enoxaparin Order — regardless of patient age. This
    subsumes the original Issue #1306 pediatric gate (which was scoped
    to age < 15); adults now also route through the enricher, which
    keeps the LOS ≥ 48 h / therapeutic-AC-active / contraindication
    checks in ONE place.
    """
    for age in (None, 3, 14, 15, 45, 80):
        orders = _run(_protocol_with_fallback_supportive(), age=age)
        assert not _has_enoxaparin(orders), (
            f"age={age} still received Enoxaparin from the fallback path — "
            "single-source-of-truth violation for DVT chemoprophylaxis"
        )


def test_pediatric_still_gets_iv_fluid_after_1342():
    # Non-DVT supportive orders are unaffected — IV_fluid still emits.
    orders = _run(_protocol_with_fallback_supportive(), age=3)
    assert _has_iv_fluid(orders)


def test_yaml_declared_dvt_prophylaxis_also_stripped_after_1342():
    # The strip applies uniformly whether DVT_prophylaxis came from the
    # hard-coded fallback or from an explicit disease-YAML declaration.
    orders = _run(_protocol_with_yaml_dvt_prophylaxis(), age=45)
    assert not _has_enoxaparin(orders)
    # Non-DVT supportive items (Positioning, IV_fluid) are preserved.
    assert _has_iv_fluid(orders)
    assert any("Positioning" in (o.display_name or "") for o in orders)
