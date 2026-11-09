"""JP labs, scales and results are named in Japanese (Issue #3031)."""

from __future__ import annotations

import re

import pytest
import yaml

from clinosim.locale.loader import lab_result_display, narrative_label
from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation, _build_vital_observations
from clinosim.modules.output.fhir_r4.labs.stage_scale_observations import build_stage_scale_observations

pytestmark = pytest.mark.unit

_LATIN_WORD = re.compile(r"[a-z]{3,}")


@pytest.mark.parametrize(
    ("value", "ja"),
    [
        ("2+ leukocytes, trace blood", "白血球(2+)、尿潜血(±)"),
        ("1+ leukocytes, nitrite positive", "白血球(1+)、亜硝酸塩(+)"),
        ("Trace protein", "尿蛋白(±)"),
        ("Glucose 1+", "尿糖(1+)"),
        ("Normal", "異常なし"),
        ("Negative", "陰性"),
        ("Positive: fentanyl, opiates", "陽性: フェンタニル、アヘン類"),
        ("A+; antibody screen negative", "A型 Rh(+)、不規則抗体スクリーニング陰性"),
    ],
)
def test_a_jp_urinalysis_result_is_japanese(value: str, ja: str) -> None:
    assert lab_result_display(value, "ja") == ja
    assert lab_result_display(value, "en") == value


def test_a_jp_urinalysis_observation_value_is_japanese() -> None:
    order = {"order_id": "o1", "display_name": "Urinalysis", "ordered_datetime": "2026-01-01T10:00:00"}
    result = {"lab_name": "Urinalysis", "value": "2+ leukocytes, trace blood", "result_datetime": "2026-01-01T11:00:00"}
    obs = _build_lab_observation(order, result, "P1", 0, "JP", encounter_id="E1")
    assert obs is not None and obs["valueString"] == "白血球(2+)、尿潜血(±)"
    assert not _LATIN_WORD.search(obs["code"]["text"])


@pytest.mark.parametrize(("country", "device"), [("JP", "経鼻カニューレ"), ("US", "nasal cannula")])
def test_the_oxygen_device_is_named(country: str, device: str) -> None:
    vs = {"on_supplemental_oxygen": True, "oxygen_flow_rate_lpm": 2, "oxygen_delivery_device": "nasal_cannula"}
    entries = _build_vital_observations(vs, "P1", 0, country, "E1")
    o2 = [e["resource"] for e in entries if e["resource"].get("component")][-1]
    assert o2["component"][-1]["valueString"] == device


def test_jp_stage_scales_are_named_in_japanese() -> None:
    patient = {
        "patient_id": "P1",
        "chronic_conditions": [{"code": "F00.9", "stage": "CDR 1"}, {"code": "G20", "stage": "H&Y 2"}],
    }
    out = build_stage_scale_observations(patient, [], None, lang="ja")
    texts = {o["code"]["text"] for o in out}
    assert texts == {"CDR全般スコア", "Hoehn-Yahr重症度"}
    assert all(o["category"][0]["text"] == "評価尺度" for o in out)
    en = build_stage_scale_observations(patient, [], None)
    assert {o["code"]["text"] for o in en} == {"Clinical Dementia Rating Global score", "Hoehn and Yahr stage"}


@pytest.mark.parametrize(("level", "ja"), [("low", "低"), ("moderate", "中"), ("high", "高")])
def test_the_fall_risk_level_is_japanese(level: str, ja: str) -> None:
    assert narrative_label("fall_risk_level", level, "ja") == ja


def test_jp_lab_panels_and_newborn_labels_have_no_english_words() -> None:
    panels = yaml.safe_load(open("clinosim/modules/observation/reference_data/lab_panels.yaml"))["panels"]
    for key in ("Lipid", "UA"):
        ja = panels[key]["display"]["ja"]
        assert not _LATIN_WORD.search(ja), ja
    for section in ("newborn_cchd_site", "newborn_cchd_body_site"):
        for key in ("right_hand", "foot"):
            assert "ductal" not in narrative_label(section, key, "ja")


def test_every_loinc_entry_has_a_japanese_label() -> None:
    codes = yaml.safe_load(open("clinosim/codes/data/loinc.yaml"))["codes"]
    assert [code for code, entry in codes.items() if isinstance(entry, dict) and not entry.get("ja")] == []


def test_every_lab_display_table_has_japanese() -> None:
    from clinosim.locale.loader import load_lab_display
    from clinosim.locale.loaders.narrative import load_lab_result_terms

    assert [k for k, v in load_lab_display().items() if not v.get("ja")] == []
    panels = yaml.safe_load(open("clinosim/modules/observation/reference_data/lab_panels.yaml"))["panels"]
    assert [k for k, p in panels.items() if not (p.get("display") or {}).get("ja")] == []
    for section, entries in load_lab_result_terms().items():
        assert all(e.get("ja") for e in entries.values()), section


def test_a_wound_culture_is_named_in_japanese() -> None:
    from clinosim.locale.loader import lab_display

    assert lab_display("Wound_culture", "ja") == "創部培養"
