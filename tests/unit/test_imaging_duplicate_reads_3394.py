"""Issue #3394: one study per modality and body site at admission, and an
abnormal read that follows the stay's diagnosis code, side and spine region."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.imaging.engine import (
    _select_report_template,
    imaging_enricher,
    imaging_laterality,
    load_body_sites,
    load_impression_templates,
)
from clinosim.modules.order.engine import drop_legacy_duplicate_imaging, place_imaging_orders
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit

T0 = datetime(2026, 3, 1, 9, 0)


def _legacy(name: str, idx: int = 0) -> Order:
    return Order(
        order_id=f"ORD-E1-ADM-I{idx:02d}",
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.IMAGING,
        display_name=name,
        ordered_datetime=T0,
        status=OrderStatus.PLACED,
    )


def _structured(modality: str, site: str, snomed: str, idx: int = 1) -> Order:
    return Order(
        order_id=f"ORD-E1-I{idx:02d}",
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.IMAGING,
        display_name="x",
        ordered_datetime=T0,
        status=OrderStatus.PLACED,
        imaging_modality=modality,
        imaging_body_site_code=snomed,
    )


def _site(key: str) -> str:
    return load_body_sites()[key]["snomed"]


def _ids(orders: list[Order]) -> list[str]:
    return [o.order_id for o in orders]


def test_legacy_order_of_a_structured_study_is_dropped() -> None:
    legacy = _legacy("Hip_Xray_AP_Lateral")
    structured = _structured("CR", "hip", _site("hip"))
    kept = drop_legacy_duplicate_imaging([legacy, structured], [structured])
    assert _ids(kept) == [structured.order_id]


def test_report_group_matches_a_region_to_the_generic_spine() -> None:
    legacy = _legacy("Cervical_Spine_CT")
    structured = _structured("CT", "spine", _site("spine"))
    assert _ids(drop_legacy_duplicate_imaging([legacy, structured], [structured])) == [structured.order_id]


def test_whole_body_ct_is_dropped_when_a_structured_ct_exists() -> None:
    legacy = _legacy("CT_Whole_Body")
    structured = _structured("CT", "head", _site("head"))
    assert _ids(drop_legacy_duplicate_imaging([legacy, structured], [structured])) == [structured.order_id]


def test_a_different_modality_or_site_is_kept() -> None:
    chest = _legacy("Chest_Xray_preop", 0)
    pelvis = _legacy("Pelvis_Xray", 1)
    ct_chest = _structured("CT", "chest", _site("chest"))
    kept = drop_legacy_duplicate_imaging([chest, pelvis, ct_chest], [ct_chest])
    assert _ids(kept) == [chest.order_id, pelvis.order_id, ct_chest.order_id]


def test_non_imaging_and_unresolvable_orders_are_kept() -> None:
    odd = _legacy("Mystery_Study_Zzz")
    lab = Order(
        order_id="ORD-E1-ADM-L00",
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.LAB,
        display_name="CBC",
        ordered_datetime=T0,
        status=OrderStatus.PLACED,
    )
    structured = _structured("CR", "chest", _site("chest"))
    assert _ids(drop_legacy_duplicate_imaging([odd, lab, structured], [structured])) == _ids([odd, lab, structured])


def test_no_structured_orders_changes_nothing() -> None:
    legacy = [_legacy("Chest_Xray", 0), _legacy("Hip_Xray_AP_Lateral", 1)]
    assert drop_legacy_duplicate_imaging(legacy, []) == legacy


def test_default_injected_chest_film_is_dropped_like_any_legacy_order() -> None:
    from clinosim.modules.disease.protocol import load_disease_protocol

    protocol = load_disease_protocol("influenza")
    counter = {"I": 0}
    structured = place_imaging_orders(protocol, "E1", "P1", T0, 0, "moderate", np.random.default_rng(1), counter)
    assert structured
    kept = drop_legacy_duplicate_imaging([_legacy("Chest_Xray_PA_Lateral")], structured)
    assert _ids(kept) == []


def _hip_record(code: str, encounter_id: str = "E7") -> SimpleNamespace:
    order = Order(
        order_id=f"ORD-{encounter_id}-I01",
        encounter_id=encounter_id,
        patient_id="P1",
        order_type=OrderType.IMAGING,
        display_name="XR Hip",
        ordered_datetime=T0,
        status=OrderStatus.PLACED,
        imaging_modality="CR",
        imaging_body_site_code=_site("hip"),
        imaging_views=["AP", "Lateral"],
        imaging_spec_meta={"abnormal_rate_by_severity": {"any": 1.0}},
    )
    return SimpleNamespace(
        patient_id="P1",
        orders=[order],
        extensions={"_disease_id": "hip_fracture"},
        severity="moderate",
        clinical_diagnosis=SimpleNamespace(admission_diagnosis_code=code),
    )


def _read(record: SimpleNamespace) -> tuple[str, str]:
    imaging_enricher(SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace()))
    report = record.extensions["imaging"][0].report
    return report.impression_text, report.impression_text_ja


@pytest.mark.parametrize(
    ("code", "en", "ja"),
    [
        ("S72.00", "femoral neck", "大腿骨頸部"),
        ("S72.10", "intertrochanteric", "転子部"),
        ("S72.2", "subtrochanteric", "転子下"),
    ],
)
def test_hip_read_follows_the_diagnosis_code_and_the_side(code: str, en: str, ja: str) -> None:
    record = _hip_record(code)
    side = imaging_laterality("E7", "hip")
    en_text, ja_text = _read(record)
    assert en in en_text
    assert ja in ja_text
    assert side in en_text
    assert ("左" if side == "left" else "右") in ja_text
    assert "{" not in en_text + ja_text


def test_one_stay_one_side_in_the_read_and_the_study() -> None:
    for i in range(12):
        record = _hip_record("S72.00", f"E{i}")
        en_text, _ = _read(record)
        study = record.extensions["imaging"][0]
        assert study.laterality in en_text


def _spine_record(disease: str, code: str, site: str, rate: float = 1.0) -> SimpleNamespace:
    order = Order(
        order_id="ORD-E9-I01",
        encounter_id="E9",
        patient_id="P1",
        order_type=OrderType.IMAGING,
        display_name="CT spine",
        ordered_datetime=T0,
        status=OrderStatus.PLACED,
        imaging_modality="CT",
        imaging_body_site_code=_site(site),
        imaging_spec_meta={"abnormal_rate_by_severity": {"any": rate}},
    )
    return SimpleNamespace(
        patient_id="P1",
        orders=[order],
        extensions={"_disease_id": disease},
        severity="moderate",
        clinical_diagnosis=SimpleNamespace(admission_diagnosis_code=code),
    )


def test_spine_read_follows_the_coded_region() -> None:
    assert "L1" in _read(_spine_record("fall_from_height", "S32.0", "spine"))[0]
    assert "T12" in _read(_spine_record("fall_from_height", "S22.0", "spine"))[0]


def test_spine_is_read_clear_when_the_injury_is_elsewhere() -> None:
    for code in ("S72.0", "S06.9"):
        text = _read(_spine_record("fall_from_height", code, "spine"))[0]
        assert "no fracture" in text.lower()


def test_a_cervical_order_is_never_read_as_an_l1_burst() -> None:
    for code in ("T07", "S32.0", "S22.0", "S72.0", "S06.9", ""):
        for rate in (0.0, 1.0):
            text = _read(_spine_record("fall_from_height", code, "cervical_spine", rate))[0]
            assert "L1" not in text and "T12" not in text


def test_the_abnormal_draw_is_unchanged_by_the_code() -> None:
    """The one random draw per study stays where it was: the same stream gives
    the same normal/abnormal outcome whatever the diagnosis code."""
    outcomes = set()
    for code in ("S72.0", "S32.0", ""):
        rng = np.random.default_rng(5)
        kind, _ = _select_report_template("fall_from_height", "CT", "spine", "moderate", {"any": 0.5}, rng, code, "")
        outcomes.add((kind if code == "S32.0" else "x", float(rng.random())))
    assert len({o[1] for o in outcomes}) == 1


def test_every_structured_imaging_order_has_a_template() -> None:
    import glob

    import yaml

    templates = load_impression_templates()
    body_sites = load_body_sites()
    missing = []
    for path in sorted(glob.glob("clinosim/modules/disease/reference_data/*.yaml")):
        data = yaml.safe_load(open(path, encoding="utf-8"))
        disease = path.rsplit("/", 1)[-1][:-5]
        for spec in (data or {}).get("imaging_orders") or []:
            site = spec["body_site"]
            keys = {
                f"{spec['modality']}_{site}",
                f"{spec['modality']}_{body_sites[site].get('report_template_site') or site}",
            }
            if modality_bucket := templates.get(disease):
                if not keys & set(modality_bucket):
                    missing.append((disease, sorted(keys)))
    # ECG / angiography / echo studies are read from the patient state (cardiac_report), not a template.
    assert not [m for m in missing if not m[1][0].startswith(("ECG", "XA"))], missing


def test_side_placeholder_only_on_paired_sites_and_in_both_languages() -> None:
    body_sites = load_body_sites()

    def texts(variant: dict):
        for slot in ("normal", "abnormal"):
            if isinstance(variant.get(slot), dict):
                yield from (variant[slot][part] for part in ("findings", "impression"))
        for entry in (variant.get("abnormal_by_code") or {}).values():
            if isinstance(entry, dict):
                yield from (entry[part] for part in ("findings", "impression"))

    for disease, buckets in load_impression_templates().items():
        for key, variant in buckets.items():
            site = key.split("_", 1)[1]
            for entry in texts(variant):
                if "{side}" in entry["en"] or "{side}" in entry["ja"]:
                    assert "{side}" in entry["en"] and "{side}" in entry["ja"], (disease, key)
                    # Issue #3557: a stroke's head study names the lesion side.
                    stroke_head = site == "head" and disease in ("cerebral_infarction", "hemorrhagic_stroke")
                    assert (body_sites.get(site) or {}).get("paired") or stroke_head, (disease, key)
