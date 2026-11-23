"""Last known well of an acute stroke admission (Issue #3558)."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta

import pytest

from clinosim.simulator.stroke_onset import last_known_well, stroke_onset_rules

ARRIVAL = datetime(2026, 6, 20, 19, 0)


def _minutes(country: str, n: int = 400) -> list[float]:
    out = []
    for i in range(n):
        lkw = last_known_well(f"ENC-{i}", "cerebral_infarction", ARRIVAL, country)
        assert lkw is not None
        out.append((ARRIVAL - lkw).total_seconds() / 60)
    return out


def test_non_stroke_has_no_last_known_well() -> None:
    assert last_known_well("ENC-1", "sepsis", ARRIVAL, "us") is None


@pytest.mark.parametrize("disease", ["cerebral_infarction", "hemorrhagic_stroke"])
def test_stroke_diseases_are_covered_and_precede_arrival(disease: str) -> None:
    lkw = last_known_well("ENC-1", disease, ARRIVAL, "japan")
    assert lkw is not None and lkw < ARRIVAL


def test_deterministic_per_encounter_id() -> None:
    a = last_known_well("ENC-7", "cerebral_infarction", ARRIVAL, "us")
    assert a == last_known_well("ENC-7", "cerebral_infarction", ARRIVAL, "us")
    assert a != last_known_well("ENC-8", "cerebral_infarction", ARRIVAL, "us")


def test_interval_stays_within_the_clamp() -> None:
    rules = stroke_onset_rules()
    for m in _minutes("us") + _minutes("japan"):
        assert rules.min_minutes <= m <= rules.max_minutes + 1


def test_us_median_matches_registry() -> None:
    assert 120 <= statistics.median(_minutes("us")) <= 195


def test_japan_arrives_within_3h_about_38_percent() -> None:
    share = sum(m <= 180 for m in _minutes("japan", 800)) / 800
    assert 0.30 <= share <= 0.46


def test_unknown_country_uses_default() -> None:
    assert last_known_well("ENC-1", "cerebral_infarction", ARRIVAL, "zz") == last_known_well(
        "ENC-1", "cerebral_infarction", ARRIVAL, stroke_onset_rules().default
    )


def test_interval_is_whole_minutes() -> None:
    lkw = last_known_well("ENC-3", "cerebral_infarction", ARRIVAL, "us")
    assert lkw is not None and (ARRIVAL - lkw) % timedelta(minutes=1) == timedelta(0)


# --- Narrative and FHIR ----------------------------------------------------


def _hp_ctx(lang: str, last_known_well: object, doc_type: object = None) -> object:
    from types import SimpleNamespace

    from clinosim.types.document import DocumentType
    from tests.unit.modules.document.narrative.test_hospital_course_3246 import _ctx

    ctx = _ctx(lang, doc=doc_type or DocumentType.ADMISSION_HP, day_index=0)
    ctx.encounter = SimpleNamespace(
        encounter_id="enc-3246",
        admission_datetime=ARRIVAL,
        discharge_datetime=None,
        encounter_type=SimpleNamespace(value="inpatient"),
        last_known_well=last_known_well,
    )
    return ctx


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "Last known well: 2026-06-20 14:30."), ("ja", "最終健常確認時刻: 2026-06-20 14:30。")],
)
@pytest.mark.parametrize("value", [datetime(2026, 6, 20, 14, 30), "2026-06-20T14:30:00"])
def test_hp_and_ed_note_state_last_known_well(lang: str, expected: str, value: object) -> None:
    from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
    from clinosim.types.document import DocumentType

    for doc in (DocumentType.ADMISSION_HP, DocumentType.ED_NOTE):
        text, facts = build_hpi(TemplateNarrativeGenerator(), _hp_ctx(lang, value, doc))  # type: ignore[arg-type]
        assert expected in text and "ctx.encounter.last_known_well" in facts


def test_no_last_known_well_no_sentence() -> None:
    from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    text, facts = build_hpi(TemplateNarrativeGenerator(), _hp_ctx("en", None))  # type: ignore[arg-type]
    assert "Last known well" not in text and "ctx.encounter.last_known_well" not in facts


def test_progress_note_does_not_repeat_last_known_well() -> None:
    from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
    from clinosim.types.document import DocumentType

    ctx = _hp_ctx("en", datetime(2026, 6, 20, 14, 30), DocumentType.PROGRESS_NOTE)
    assert "Last known well" not in build_hpi(TemplateNarrativeGenerator(), ctx)[0]  # type: ignore[arg-type]


def test_stroke_condition_begins_at_last_known_well() -> None:
    from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions

    def build(lkw: str | None) -> dict:
        enc = {
            "encounter_id": "enc-1",
            "encounter_type": "inpatient",
            "admission_datetime": "2026-06-20T19:00:00",
            "discharge_datetime": "2026-06-25T11:00:00",
        }
        if lkw:
            enc["last_known_well"] = lkw
        record = {"clinical_diagnosis": {"discharge_diagnosis_code": "I63.9"}, "encounters": [enc], "patient": {}}
        conds = _build_conditions(record, "pat-1", "US")
        return next(c for c in conds if "enc-1-primary" in str(c.get("identifier")))

    with_lkw, without = build("2026-06-20T14:30:00"), build(None)
    assert with_lkw["onsetDateTime"].startswith("2026-06-20T14:30")
    assert with_lkw["recordedDate"].startswith("2026-06-20T19:00")
    assert without["onsetDateTime"].startswith("2026-06-20T19:00")
