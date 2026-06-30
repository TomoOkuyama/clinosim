"""Unit tests for imaging order placement (Tier 1 #2 PR1)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.order.engine import place_imaging_orders
from clinosim.types.encounter import OrderType


class _StubProtocol:
    """Minimal DiseaseProtocol stub for testing place_imaging_orders directly."""

    def __init__(self, imaging_orders):
        self.imaging_orders = imaging_orders


def _make_spec(**overrides):
    base = {
        "modality": "CR",
        "body_site": "chest",
        "views": ["PA", "Lateral"],
        "urgency": "routine",
        "clinical_indication": "Suspected pneumonia",
        "day": 0,
        "contrast": False,
        "only_if_severity": [],
        "abnormal_rate_by_severity": {"mild": 0.85, "moderate": 0.95, "severe": 1.0},
    }
    base.update(overrides)
    return base


def test_places_cr_chest_order_on_admission_day():
    protocol = _StubProtocol([_make_spec()])
    rng = np.random.default_rng(42)
    orders = place_imaging_orders(
        protocol, encounter_id="enc1", patient_id="pt1",
        admission_dt=datetime(2026, 6, 30, 8, 0),
        day_index=0, severity="moderate", rng=rng, sequence_counter={"L": 0, "I": 0},
    )
    assert len(orders) == 1
    o = orders[0]
    assert o.order_type == OrderType.IMAGING
    assert o.imaging_modality == "CR"
    assert o.imaging_body_site_code == "51185008"  # chest SNOMED
    assert o.imaging_views == ["PA", "Lateral"]
    assert o.urgency == "routine"
    assert o.clinical_intent == "Suspected pneumonia"
    # order_code must be the resolved procedure code (LOINC for default lookup, e.g. CR_PA_Lateral)
    assert o.order_code == "36572-6"   # LOINC for "Chest X-ray PA and Lateral"
    assert o.imaging_spec_meta == {"abnormal_rate_by_severity": {"mild": 0.85, "moderate": 0.95, "severe": 1.0}}


def test_skips_when_only_if_severity_unsatisfied():
    spec = _make_spec(day=1, only_if_severity=["moderate", "severe"])
    protocol = _StubProtocol([spec])
    rng = np.random.default_rng(42)
    orders = place_imaging_orders(
        protocol, encounter_id="enc1", patient_id="pt1",
        admission_dt=datetime(2026, 6, 30, 8, 0),
        day_index=1, severity="mild", rng=rng, sequence_counter={"L": 0, "I": 0},
    )
    assert orders == []


def test_skips_when_day_does_not_match():
    """Day 0 spec must not fire on day_index=2."""
    spec = _make_spec(day=0)
    protocol = _StubProtocol([spec])
    rng = np.random.default_rng(42)
    orders = place_imaging_orders(
        protocol, encounter_id="enc1", patient_id="pt1",
        admission_dt=datetime(2026, 6, 30, 8, 0),
        day_index=2, severity="moderate", rng=rng, sequence_counter={"L": 0, "I": 0},
    )
    assert orders == []


def test_empty_imaging_orders_returns_empty_list():
    protocol = _StubProtocol([])
    rng = np.random.default_rng(42)
    orders = place_imaging_orders(
        protocol, encounter_id="enc1", patient_id="pt1",
        admission_dt=datetime(2026, 6, 30, 8, 0),
        day_index=0, severity="moderate", rng=rng, sequence_counter={"L": 0, "I": 0},
    )
    assert orders == []


def test_ct_head_uses_correct_procedure_code():
    spec = _make_spec(modality="CT", body_site="head",
                      views=[], clinical_indication="Suspected ICH")
    protocol = _StubProtocol([spec])
    rng = np.random.default_rng(42)
    orders = place_imaging_orders(
        protocol, encounter_id="enc1", patient_id="pt1",
        admission_dt=datetime(2026, 6, 30, 8, 0),
        day_index=0, severity="severe", rng=rng, sequence_counter={"L": 0, "I": 0},
    )
    assert len(orders) == 1
    o = orders[0]
    assert o.imaging_modality == "CT"
    assert o.imaging_body_site_code == "69536005"   # head SNOMED
    assert o.order_code == "30799-1"                # LOINC CT Head non-contrast
    # Empty views → default_views_by_body_site applied
    assert o.imaging_views == ["axial"]


def test_raises_on_unknown_body_site():
    spec = _make_spec(body_site="unknown_site")
    protocol = _StubProtocol([spec])
    rng = np.random.default_rng(42)
    with pytest.raises(ValueError, match="body_sites.yaml"):
        place_imaging_orders(
            protocol, encounter_id="enc1", patient_id="pt1",
            admission_dt=datetime(2026, 6, 30, 8, 0),
            day_index=0, severity="moderate", rng=rng,
            sequence_counter={"L": 0, "I": 0},
        )


def test_raises_on_unknown_modality():
    spec = _make_spec(modality="XR")  # XR not in modalities.yaml (only CR + CT)
    protocol = _StubProtocol([spec])
    rng = np.random.default_rng(42)
    with pytest.raises(ValueError, match="modalities.yaml"):
        place_imaging_orders(
            protocol, encounter_id="enc1", patient_id="pt1",
            admission_dt=datetime(2026, 6, 30, 8, 0),
            day_index=0, severity="moderate", rng=rng,
            sequence_counter={"L": 0, "I": 0},
        )
