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


def test_adult_still_gets_enoxaparin_from_fallback():
    orders = _run(_protocol_with_fallback_supportive(), age=45)
    assert _has_enoxaparin(orders)


def test_pediatric_3yo_skips_enoxaparin_from_fallback():
    orders = _run(_protocol_with_fallback_supportive(), age=3)
    assert not _has_enoxaparin(orders)
    # Other supportive orders unaffected — IV_fluid still there.
    assert _has_iv_fluid(orders)


def test_pediatric_14yo_skips_enoxaparin_from_fallback():
    # Ceiling is exclusive (age < 15 → skip); 14 hits the gate.
    orders = _run(_protocol_with_fallback_supportive(), age=14)
    assert not _has_enoxaparin(orders)


def test_15yo_gets_enoxaparin_from_fallback():
    # 15 is the ceiling; age >= 15 does NOT skip.
    orders = _run(_protocol_with_fallback_supportive(), age=15)
    assert _has_enoxaparin(orders)


def test_pediatric_skips_yaml_declared_dvt_prophylaxis():
    orders = _run(_protocol_with_yaml_dvt_prophylaxis(), age=6)
    assert not _has_enoxaparin(orders)
    # Other yaml-declared supportive items (Positioning, IV_fluid) unaffected.
    assert _has_iv_fluid(orders)
    assert any("Positioning" in (o.display_name or "") for o in orders)


def test_omitting_patient_age_preserves_pre_1306_behavior():
    # Backwards compat: callers that don't pass patient_age get the
    # old behavior (no age gate). This matters for any legacy callers
    # of place_admission_orders (tests, older adapters).
    orders = _run(_protocol_with_fallback_supportive(), age=None)
    assert _has_enoxaparin(orders)
