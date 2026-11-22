"""Issue #3557: the workup MRI of an acute stroke is read at the protocol's
abnormal rate, and the lesion side is one canonical value per stay, opposite
to the side of the weakness the admission exam writes."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.disease.laterality import stroke_lesion_side, stroke_weakness_side
from clinosim.modules.imaging.engine import imaging_enricher, load_body_sites, workup_abnormal_rate
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit

T0 = datetime(2026, 3, 1, 9, 0)


def _stroke_record(encounter_id: str, disease: str = "cerebral_infarction", site: str = "head") -> SimpleNamespace:
    """A stay whose MRI is a free-text workup order (no imaging_spec_meta)."""
    order = Order(
        order_id=f"ORD-{encounter_id}-I01",
        encounter_id=encounter_id,
        patient_id="P1",
        order_type=OrderType.IMAGING,
        display_name="MRI_brain_DWI",
        ordered_datetime=T0,
        status=OrderStatus.PLACED,
        imaging_modality="MR",
        imaging_body_site_code=load_body_sites()[site]["snomed"],
    )
    return SimpleNamespace(
        patient_id="P1",
        orders=[order],
        extensions={"_disease_id": disease},
        severity="severe",
        clinical_diagnosis=SimpleNamespace(admission_diagnosis_code="I63.9"),
    )


def _read(record: SimpleNamespace) -> str:
    imaging_enricher(SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace()))
    return record.extensions["imaging"][0].report.impression_text


def test_workup_rate_comes_from_the_protocol_imaging_order() -> None:
    assert workup_abnormal_rate("cerebral_infarction", "MR", "head")["severe"] == 1.0
    assert workup_abnormal_rate("cerebral_infarction", "MR", "chest") == {}
    assert workup_abnormal_rate("", "MR", "head") == {}


def test_severe_stroke_workup_mri_is_read_as_infarct() -> None:
    for i in range(20):
        assert "infarct" in _read(_stroke_record(f"ENC-{i}"))


def test_lesion_is_contralateral_to_the_weakness_and_canonical() -> None:
    sides = set()
    for i in range(40):
        enc = f"ENC-{i}"
        weak, lesion = stroke_weakness_side(enc), stroke_lesion_side(enc)
        assert {weak, lesion} == {"left", "right"}
        text = _read(_stroke_record(enc))
        assert f"the {lesion} MCA territory" in text
        sides.add(lesion)
    assert sides == {"left", "right"}


def test_exam_weakness_side_uses_the_canonical_helper() -> None:
    from clinosim.modules.document.narrative.renderers._disease_exam import stroke_deficit
    from tests.unit.modules.document.narrative.test_admission_hp_exam_3245 import _ctx

    ctx = _ctx("cerebral_infarction", "en")
    weak = stroke_weakness_side("ENC-77")
    assert f"{weak} " in stroke_deficit(ctx, with_nihss=False)


def test_hemorrhagic_stroke_head_ct_names_the_lesion_side() -> None:
    rec = _stroke_record("ENC-3", disease="hemorrhagic_stroke")
    rec.orders[0].imaging_modality = "CT"
    text = _read(rec)
    assert f"{stroke_lesion_side('ENC-3')} basal ganglia" in text or "No acute" in text
