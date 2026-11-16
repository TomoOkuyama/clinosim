"""The inpatient progress-note Assessment states only what the note's writer
knew (Issues #3229 / #3241) and ranks the day's labs by clinical priority
(Issue #3230)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._replacement_renderers import _render_abnormal_labs
from clinosim.modules.document.narrative.lab_timeseries import select_notable_labs
from clinosim.modules.document.narrative.renderers._composers import compose_progress_assessment_from_state
from clinosim.modules.observation.engine import format_lab_value

pytestmark = pytest.mark.unit

ADMIT = "2026-02-24T18:00:00"


def _ctx(lang="en", *, day=0, labs=(), events=(), authored=None, names=None):
    return SimpleNamespace(
        target_lang=lang,
        day_index=day,
        lab_results=list(labs),
        complications_events=list(events),
        complications_occurred=list(names if names is not None else [e["name"] for e in events]),
        encounter={"admission_datetime": ADMIT},
        authored_datetime=authored,
    )


def _lab(name, value, flag, at, unit=""):
    return {"lab_name": name, "value": value, "unit": unit, "flag": flag, "result_datetime": at}


# --- Issue #3229: complications from their onset day -----------------------

_CEREBRAL_EDEMA = {"name": "cerebral_edema", "onset_day": 3, "onset_datetime": "2026-02-27T12:00:00"}


@pytest.mark.parametrize("day", [0, 1, 2])
def test_no_complication_before_its_onset_day(day: int) -> None:
    out = compose_progress_assessment_from_state(_ctx(day=day, events=[_CEREBRAL_EDEMA]))
    assert "edema" not in out.lower()


def test_complication_is_new_on_its_onset_day_and_ongoing_after() -> None:
    onset = compose_progress_assessment_from_state(
        _ctx(day=3, events=[_CEREBRAL_EDEMA], authored=datetime(2026, 2, 27, 20, 0))
    )
    assert onset.startswith("New complication (cerebral edema)")
    later = compose_progress_assessment_from_state(_ctx(day=4, events=[_CEREBRAL_EDEMA]))
    assert later.startswith("Complications noted (cerebral edema)")


def test_complication_later_on_the_note_day_is_not_yet_known() -> None:
    out = compose_progress_assessment_from_state(
        _ctx(day=3, events=[_CEREBRAL_EDEMA], authored=datetime(2026, 2, 27, 9, 0))
    )
    assert "edema" not in out


def test_complication_after_one_note_is_new_in_the_next() -> None:
    out = compose_progress_assessment_from_state(
        _ctx(day=4, events=[_CEREBRAL_EDEMA], authored=datetime(2026, 2, 28, 9, 0))
    )
    assert out.startswith("New complication (cerebral edema)")


def test_ja_complication_new_and_ongoing() -> None:
    onset = compose_progress_assessment_from_state(_ctx("ja", day=3, events=[_CEREBRAL_EDEMA]))
    later = compose_progress_assessment_from_state(_ctx("ja", day=5, events=[_CEREBRAL_EDEMA]))
    assert "新たに 脳浮腫 を合併" in onset
    assert "合併症" in later and "対応継続中" in later


def test_undated_complication_is_left_out_of_a_day_note() -> None:
    legacy = {"name": "pneumothorax", "onset_day": None, "onset_datetime": None, "source": "legacy"}
    for lang in ("en", "ja"):
        out = compose_progress_assessment_from_state(_ctx(lang, day=4, events=[legacy]))
        assert "pneumothorax" not in out.lower() and "気胸" not in out


# --- Issue #3230: ranked, one per analyte, formatted, interpreted ---------------


def _day9_labs():
    return [
        _lab("Glucose", 167.0, "H", "2026-03-04T06:10:00", "mg/dL"),  # day 8
        _lab("Creatinine", 1.72, "H", "2026-03-03T07:00:00", "mg/dL"),  # day 7
        _lab("Glucose", 171.0, "H", "2026-03-05T06:00:00", "mg/dL"),
        _lab("Troponin_I", 86.621, "H", "2026-03-05T06:30:00", "ng/mL"),
        _lab("Creatinine", 4.21, "H", "2026-03-05T07:00:00", "mg/dL"),
        _lab("Glucose", 172.0, "H", "2026-03-05T11:00:00", "mg/dL"),
        _lab("Glucose", 178.0, "H", "2026-03-05T16:00:00", "mg/dL"),
        _lab("K", 8.5, "critical", "2026-03-05T18:30:00", "mmol/L"),
    ]


def test_critical_potassium_first_one_glucose_and_interpretations() -> None:
    out = compose_progress_assessment_from_state(_ctx(day=9, labs=_day9_labs(), authored=datetime(2026, 3, 5, 20, 3)))
    labs = out.split("Notable labs (past 24 h): ")[1]
    assert labs.startswith("K 8.5 mmol/L [critical] (hyperkalemia)")
    assert labs.count("glucose") == 1
    assert "glucose 178 mg/dL [H] (prior 172)" in labs
    assert "creatinine 4.21 mg/dL [H] (prior 1.72; AKI by KDIGO criteria)" in labs
    assert "troponin elevation" in labs
    # The three interpreted analytes come before the persisting glucose.
    assert labs.index("creatinine") < labs.index("glucose")
    assert labs.index("troponin") < labs.index("glucose")


def test_hemolyzed_potassium_is_named_as_such_not_as_hyperkalemia() -> None:
    labs = [_lab("K", 8.5, "H*", "2026-03-05T18:30:00", "mmol/L")]
    out = compose_progress_assessment_from_state(_ctx(day=9, labs=labs))
    assert "K 8.5 mmol/L [H*] (hemolyzed specimen, repeat)" in out
    assert "hyperkalemia" not in out


def test_identical_duplicates_render_once_en_and_ja() -> None:
    labs = [_lab("Glucose", 202.0, "H", "2026-02-26T06:00:00", "mg/dL")] * 2 + [
        _lab("CRP", 3.63, "H", "2026-02-26T06:00:00", "mg/dL")
    ]
    en = compose_progress_assessment_from_state(_ctx(day=2, labs=labs))
    ja = compose_progress_assessment_from_state(_ctx("ja", day=2, labs=labs))
    assert en.count("glucose 202 mg/dL") == 1
    assert ja.count("血糖 202 mg/dL") == 1
    assert "CRP 3.63" in ja


def test_integer_analyte_prints_without_trailing_zero() -> None:
    labs = [_lab("WBC", 13214.0, "H", "2026-02-26T06:00:00", "/uL")]
    out = compose_progress_assessment_from_state(_ctx(day=2, labs=labs))
    assert "13214 " in out and "13214.0" not in out
    assert format_lab_value("Creatinine", 1.7, "mg/dL") == "1.70"
    assert format_lab_value("CRP", 3.63, "mg/dL") == "3.63"  # JP reporting unit keeps its digits


def test_more_than_the_cap_counts_the_rest() -> None:
    names = ["AST", "ALT", "ALP", "GGT", "LDH", "CK"]
    labs = [_lab(n, 500.0, "H", f"2026-02-26T0{i}:00:00", "U/L") for i, n in enumerate(names)]
    out = compose_progress_assessment_from_state(_ctx(day=2, labs=labs))
    assert out.endswith("+2 other abnormal.")


def test_finding_named_only_beyond_its_definition() -> None:
    def finding(name, value, flag):
        labs = [_lab(name, value, flag, "2026-02-26T06:00:00", "mmol/L")]
        return [p.finding for p in select_notable_labs(labs, ADMIT, 2)]

    assert finding("K", 5.0, "H") == [None]  # above a JCCLS interval only
    assert finding("K", 6.8, "critical") == ["hyperkalemia"]
    assert finding("Na", 136.0, "L") == [None]
    assert finding("Na", 132.0, "L") == ["hyponatremia"]


def test_creatinine_rise_by_absolute_amount_within_48h_is_aki() -> None:
    labs = [
        _lab("Creatinine", 1.0, None, "2026-02-25T06:00:00", "mg/dL"),
        _lab("Creatinine", 1.35, "H", "2026-02-26T06:00:00", "mg/dL"),
    ]
    picks = select_notable_labs(labs, ADMIT, 2)
    assert [p.finding for p in picks] == ["aki"]
    labs[0]["result_datetime"] = "2026-02-23T06:00:00"  # 72 h before: neither criterion
    assert [p.finding for p in select_notable_labs(labs, ADMIT, 2)] == [None]


# --- Issue #3241: only results reported by the note's authored time -------------


def test_day_one_note_excludes_results_reported_after_it() -> None:
    labs = [
        _lab("AST", 132.0, "H", "2026-02-24T22:22:00", "U/L"),
        _lab("PT_INR", 1.4, "H", "2026-02-24T17:30:00", ""),
    ]
    out = compose_progress_assessment_from_state(_ctx(day=0, labs=labs, authored=datetime(2026, 2, 24, 18, 35)))
    assert "AST" not in out
    assert "PT-INR 1.4" in out or "PT_INR 1.4" in out


def test_result_after_one_note_is_cited_by_the_next() -> None:
    labs = [_lab("AST", 132.0, "H", "2026-02-24T22:22:00", "U/L")]
    out = compose_progress_assessment_from_state(_ctx(day=1, labs=labs, authored=datetime(2026, 2, 25, 18, 35)))
    assert "Notable labs (past 24 h): AST 132 U/L [H]." in out
    ja = compose_progress_assessment_from_state(_ctx("ja", day=1, labs=labs, authored=datetime(2026, 2, 25, 18, 35)))
    assert "直近24時間の検査所見: AST 132 U/L [H]。" in ja


def test_llm_context_uses_the_same_selection_and_cut_off() -> None:
    labs = _day9_labs()
    text = _render_abnormal_labs(labs, 9, "en", admission_datetime=ADMIT, as_of=datetime(2026, 3, 5, 12, 0))
    assert "K 8.5" not in text  # reported 18:30, after the cut-off
    assert text.count("glucose") == 1
    assert text == (
        "troponin I 86.621 ng/mL [H] (troponin elevation); "
        "creatinine 4.21 mg/dL [H] (prior 1.72; AKI by KDIGO criteria); "
        "glucose 172 mg/dL [H] (prior 171)"
    )
