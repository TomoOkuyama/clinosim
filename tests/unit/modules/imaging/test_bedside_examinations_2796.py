"""Issue #2796: bedside eye examinations on the imaging work-up list get no
ImagingStudy and no radiology report."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.imaging.engine import bedside_examination_names, imaging_enricher
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit


def _order(i: int, name: str) -> Order:
    return Order(
        order_id=f"ORD-enc1-ED-I{i}",
        encounter_id="enc1",
        patient_id="pt1",
        order_type=OrderType.IMAGING,
        display_name=name,
        urgency="stat",
        ordered_datetime=datetime(2026, 6, 30, 8, 30 + i),
        status=OrderStatus.PLACED,
    )


def _studies(names: list[str]) -> list:
    record = SimpleNamespace(
        patient_id="pt1",
        orders=[_order(i, n) for i, n in enumerate(names)],
        extensions={},
        disease_id="eye_foreign_body",
        severity="mild",
    )
    imaging_enricher(
        SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace(modules=SimpleNamespace()))
    )
    return record.extensions.get("imaging", [])


def test_the_eye_examinations_are_bedside_examinations() -> None:
    assert {"Slit_lamp_exam", "Fluorescein_stain"} <= bedside_examination_names()


def test_a_bedside_examination_gets_no_imaging_study() -> None:
    assert _studies(["Slit_lamp_exam", "Fluorescein_stain"]) == []


def test_an_imaging_order_beside_it_still_gets_its_study() -> None:
    studies = _studies(["Slit_lamp_exam", "CT_Head"])
    assert [s.description for s in studies] == ["CT_Head"]
