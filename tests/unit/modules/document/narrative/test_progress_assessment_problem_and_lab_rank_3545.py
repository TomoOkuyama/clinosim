"""The progress-note Assessment states the problem and ranks the day's labs by
clinical relevance (Issue #3545)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
    NotableLabRules,
    notable_lab_rules,
)
from clinosim.modules.document.narrative.lab_timeseries import select_notable_labs
from clinosim.modules.document.narrative.renderers._composers import compose_progress_assessment_from_state

pytestmark = pytest.mark.unit

ADMIT = "2026-08-23T18:00:00"
NOTE = datetime(2026, 8, 24, 5, 4)


def _lab(name, value, flag, at):
    return {"lab_name": name, "value": value, "unit": "", "flag": flag, "result_datetime": at}


def _day1_labs():
    """Chronic markers reported first, the acute markers after them."""
    return [
        _lab("Glucose", 121, "H", "2026-08-24T00:10:00"),
        _lab("HDL", 43, "L", "2026-08-24T00:11:00"),
        _lab("LDL", 108, "H", "2026-08-24T00:12:00"),
        _lab("TG", 210, "H", "2026-08-24T00:13:00"),
        _lab("TC", 230, "H", "2026-08-24T00:14:00"),
        _lab("PCT", 2.05, "H", "2026-08-24T01:51:00"),
        _lab("CRP", 234.3, "H", "2026-08-24T01:52:00"),
        _lab("Lactate", 4.9, "H", "2026-08-24T01:56:00"),
    ]


def test_acute_markers_are_named_before_chronic_ones() -> None:
    picks = select_notable_labs(_day1_labs(), ADMIT, 1, as_of=NOTE)
    names = [p.lab["lab_name"] for p in picks]
    shown = names[: notable_lab_rules().max_items.note]
    assert {"Lactate", "CRP", "PCT"} <= set(shown)
    assert names.index("Lactate") < names.index("Glucose")
    assert names.index("CRP") < names.index("LDL")


def test_a_panic_result_still_leads() -> None:
    labs = [*_day1_labs(), _lab("K", 7.0, "critical", "2026-08-24T02:00:00")]
    assert select_notable_labs(labs, ADMIT, 1, as_of=NOTE)[0].lab["lab_name"] == "K"


def test_chronic_markers_come_last_among_the_rest() -> None:
    labs = [*_day1_labs(), _lab("ALT", 90, "H", "2026-08-24T02:00:00")]
    names = [p.lab["lab_name"] for p in select_notable_labs(labs, ADMIT, 1, as_of=NOTE)]
    assert names.index("ALT") < names.index("LDL")


def test_relevance_table_is_validated_against_known_analytes() -> None:
    data = notable_lab_rules().model_dump()
    data["relevance"]["acute_phase"] = ["NotAnAnalyte"]
    with pytest.raises(ValueError, match="unknown lab analytes"):
        NotableLabRules.model_validate(data)


def _ctx(lang="en", day=1, *, labs=(), dx="J18.9", wds=()):
    return SimpleNamespace(
        target_lang=lang,
        day_index=day,
        lab_results=list(labs),
        complications_events=[],
        complications_occurred=[],
        encounter={"admission_datetime": ADMIT},
        authored_datetime=NOTE,
        orders=[],
        locale="us",
        patient=None,
        diagnoses=[{"admission_diagnosis_code": dx, "discharge_diagnosis_code": "N17.9"}] if dx else [],
        working_diagnoses=list(wds),
    )


def test_assessment_leads_with_the_admission_diagnosis() -> None:
    out = compose_progress_assessment_from_state(_ctx(labs=_day1_labs()))
    assert out.startswith("Problem: ")
    assert "J18.9" in out.split(".")[0] + "." or "J18.9" in out[:120]
    assert out.index("Problem") < out.index("Notable labs")
    assert "lactate" in out.lower()


def test_assessment_does_not_name_the_discharge_diagnosis() -> None:
    out = compose_progress_assessment_from_state(_ctx(labs=_day1_labs()))
    assert "N17" not in out


def test_in_hospital_working_diagnosis_is_not_named_before_its_onset() -> None:
    wd = {"disease_id": "N17.9", "onset_day": 5}
    out = compose_progress_assessment_from_state(_ctx(labs=_day1_labs(), wds=[wd]))
    assert "N17" not in out


def test_ja_assessment_leads_with_the_problem() -> None:
    out = compose_progress_assessment_from_state(_ctx("ja", labs=_day1_labs()))
    assert out.startswith("主病態: ")
    assert out.index("主病態") < out.index("検査所見")


def test_no_diagnosis_no_problem_line() -> None:
    out = compose_progress_assessment_from_state(_ctx(labs=_day1_labs(), dx=""))
    assert "Problem" not in out
