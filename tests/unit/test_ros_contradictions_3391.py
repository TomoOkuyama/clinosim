"""Issue #3391: a trauma ROS never denies what the encounter's head imaging or
arrival consciousness shows."""

from __future__ import annotations

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative._ros_contradictions import RULES
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.hpi import _ros_line
from clinosim.modules.document.reference_data_loaders import (
    ROS_CONTRADICTION_RULES,
    HpiPertinentNegatives,
    load_hpi_pertinent_negatives,
)
from clinosim.modules.imaging.engine import imaging_report_is_abnormal, load_impression_templates
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_HEAD = "69536005"
_TEMPLATE = load_impression_templates()["fall_from_height"]["CT_head"]
_NORMAL = _TEMPLATE["normal"]["impression"]
_ABNORMAL = _TEMPLATE["abnormal"]["impression"]


def _ctx(target: str, studies: list[dict], vitals: list[dict] | None = None):
    record = {
        "patient": {"patient_id": "P-3391", "age": 40, "sex": "M", "current_medications": [], "chronic_conditions": []},
        "encounters": [
            {"encounter_id": "E-3391", "encounter_type": "inpatient", "admission_datetime": "2026-06-21T10:00:00"}
        ],
        "extensions": {"imaging": studies},
        "vital_signs": vitals or [],
    }
    ctx = build_narrative_context(record, record["encounters"][0], DocumentType.ADMISSION_HP, 0, target)
    ctx.disease_protocol = load_disease_protocol("fall_from_height")
    return ctx


def _study(impression: dict[str, str]) -> dict:
    return {
        "encounter_id": "E-3391",
        "modality_code": "CT",
        "body_site_snomed": _HEAD,
        "report": {"impression_text": impression["en"], "impression_text_ja": impression["ja"]},
    }


@pytest.mark.parametrize(("target", "lang"), [("US", "en"), ("JP", "ja")])
def test_abnormal_head_ct_drops_the_head_and_consciousness_negatives(target: str, lang: str) -> None:
    ros = _ros_line(_ctx(target, [_study(_ABNORMAL)]), "")
    assert "head strike" not in ros and "頭部打撲" not in ros
    assert "consciousness" not in ros and "意識消失" not in ros
    assert ros  # the next surviving negative is written


@pytest.mark.parametrize("target", ["US", "JP"])
def test_normal_head_ct_keeps_the_negatives(target: str) -> None:
    ros = _ros_line(_ctx(target, [_study(_NORMAL)]), "")
    assert ("no loss of consciousness" in ros and "no head strike" in ros) or (
        "意識消失なし" in ros and "頭部打撲なし" in ros
    )


def test_unknown_read_keeps_the_negatives() -> None:
    study = _study({"en": "Something unrecognised", "ja": "未知の所見"})
    study["body_site_snomed"] = "0000"
    assert "no head strike" in _ros_line(_ctx("US", [study]), "")


def test_arrival_avpu_below_alert_drops_the_loc_negative() -> None:
    ros = _ros_line(_ctx("US", [], [{"consciousness_level": "V"}]), "")
    assert "loss of consciousness" not in ros and "head strike" not in ros


def test_gcs_below_15_drops_the_negatives() -> None:
    ros = _ros_line(_ctx("US", [], [{"consciousness_level": "A", "gcs_score": 13}]), "")
    assert "loss of consciousness" not in ros


def test_alert_arrival_without_imaging_keeps_the_negatives() -> None:
    ros = _ros_line(_ctx("US", [], [{"consciousness_level": "A", "gcs_score": 15}]), "")
    assert "no loss of consciousness" in ros


def test_report_abnormality_from_the_template() -> None:
    args = ("fall_from_height", "CT", _HEAD)
    assert imaging_report_is_abnormal(*args, (_NORMAL["en"], "")) is False
    assert imaging_report_is_abnormal(*args, ("", _NORMAL["ja"])) is False
    assert imaging_report_is_abnormal(*args, (_ABNORMAL["en"], "")) is True
    assert imaging_report_is_abnormal(*args, ("", "")) is None
    assert imaging_report_is_abnormal("no_such_disease", "CT", _HEAD, (_NORMAL["en"],)) is None


def test_unknown_rule_is_rejected_at_load() -> None:
    with pytest.raises(ValueError, match="contradicted_by"):
        HpiPertinentNegatives.model_validate({"d": [{"text": {"en": "x"}, "contradicted_by": ["nope"]}]})


def test_rule_names_match_the_evaluators() -> None:
    assert set(RULES) == ROS_CONTRADICTION_RULES


def test_every_head_and_loc_negative_is_tagged() -> None:
    for disease, entries in load_hpi_pertinent_negatives().items():
        for e in entries:
            en = e.text["en"].lower()
            if "head strike" in en or "head injury" in en or "consciousness" in en:
                assert e.contradicted_by, f"{disease}: {en!r} must carry contradicted_by"
