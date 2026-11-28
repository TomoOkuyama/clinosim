"""Issue #3972: a venous thromboembolism that is not anticoagulated because the stay's
principal diagnosis is an intracranial hemorrhage says so in the notes.

The hemorrhagic-stroke protocol declares ``start_anticoagulation_cautiously`` (DVT) and
``anticoagulation_if_safe`` (PE); the complication actions list them as not executed, so no
anticoagulant is ordered by design. The decision is recorded as a ``hold`` entry of the
stay's safety-skip log with its reason, and rendered by the existing withhold note.
"""

from __future__ import annotations

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative._safety_skips import progress_note_safety_skips, safety_skip_line
from tests.unit.simulator.test_complication_treatment_3864 import (  # noqa: F401
    DAY,
    _fire,
    _meds,
    _run,
    _stay,
    _weight,
)

pytestmark = pytest.mark.unit

_DECLARED = {"dvt": "start_anticoagulation_cautiously", "pulmonary_embolism": "anticoagulation_if_safe"}


def _ich_stay(country: str):
    stay = _stay(country)
    stay.disease_id = "hemorrhagic_stroke"
    stay.protocol = load_disease_protocol("hemorrhagic_stroke")
    return stay


def _holds(stay):
    return [e for e in stay.patient.safety_skip_log if e.event_type == "hold"]


@pytest.mark.parametrize("country", ["japan", "us"])
@pytest.mark.parametrize("complication", ["dvt", "pulmonary_embolism"])
def test_the_withhold_is_recorded_with_its_reason_and_no_anticoagulant_is_ordered(monkeypatch, country, complication):
    stay, run = _ich_stay(country), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run, complication, (_DECLARED[complication],))
    assert not _meds(run, "anticoagulant")
    assert not [o for o in run.orders if o.display_name.startswith("DISCONTINUE:")]
    (entry,) = _holds(stay)
    assert entry.candidate_drug in {"Heparin", "Rivaroxaban"}
    assert entry.verdict.rule_id == "complication-anticoagulation-withheld"
    assert entry.stopped_on_day == DAY + 1
    assert entry.substituted_with is None
    if country == "us":
        assert "intracranial hemorrhage" in entry.active_conflict
    else:
        assert "頭蓋内出血" in entry.active_conflict_ja and not entry.active_conflict_ja.isascii()


@pytest.mark.parametrize(("lang", "needle"), [("en", "intracranial hemorrhage"), ("ja", "頭蓋内出血")])
def test_the_existing_withhold_note_renders_the_reason(monkeypatch, lang, needle):
    stay, run = _ich_stay("japan"), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run, "dvt", (_DECLARED["dvt"],))
    (entry,) = _holds(stay)
    skip = {
        "event_type": "hold",
        "considered": entry.candidate_drug,
        "considered_ja": entry.candidate_drug_ja,
        "avoided_due_to": entry.active_conflict,
        "avoided_due_to_ja": entry.active_conflict_ja,
        "stopped_on_day": entry.stopped_on_day,
    }
    line = safety_skip_line(skip, lang, prefix="safety_skips")
    assert needle in line
    assert ("anticoagulation" in line) if lang == "en" else ("抗凝固" in line)
    assert ("for DVT" in line) if lang == "en" else ("深部静脈血栓症" in line)
    # the onset day's progress note states it; an earlier day's does not
    assert progress_note_safety_skips([skip], hospital_day=DAY + 1, stops={}) == [skip]
    assert progress_note_safety_skips([skip], hospital_day=DAY + 3, stops={}) == [skip]
    assert progress_note_safety_skips([skip], hospital_day=DAY, stops={}) == []


def test_a_non_hemorrhagic_stay_with_the_same_action_records_nothing(monkeypatch):
    stay, run = _stay("japan"), _run(creatinine=0.9)  # bacterial pneumonia
    _fire(monkeypatch, stay, run, "dvt", (_DECLARED["dvt"],))
    assert not _holds(stay) and not _meds(run, "anticoagulant")


def test_an_executed_anticoagulation_of_a_hemorrhagic_stay_is_unchanged(monkeypatch):
    stay, run = _ich_stay("japan"), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run, "dvt", ("start_anticoagulation",))
    assert _meds(run, "anticoagulant") and not _holds(stay)


def test_the_withhold_is_recorded_once_per_complication(monkeypatch):
    stay, run = _ich_stay("japan"), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run, "dvt", (_DECLARED["dvt"], "anticoagulation_if_safe"))
    assert len(_holds(stay)) == 1


def _withhold_skip(complication_en: str, complication_ja: str, drug: str = "Heparin", drug_ja: str = "ヘパリン"):
    from clinosim.simulator.complication_actions import complication_note_entry

    entry = complication_note_entry(
        event_type="hold",
        rule_id="complication-anticoagulation-withheld",
        matched_classes=("anticoagulant", "intracranial_hemorrhage"),
        encounter_id="enc-3246",
        drug=drug,
        drug_ja=drug_ja,
        reason_key="anticoagulant_withheld_for_intracranial_hemorrhage",
        complication={"en": complication_en, "ja": complication_ja},
        stopped_on_day=4,
        timestamp=__import__("datetime").datetime(2025, 12, 8, 12),
    )
    return {
        "considered": entry.candidate_drug,
        "considered_ja": entry.candidate_drug_ja,
        "avoided_due_to": entry.active_conflict,
        "avoided_due_to_ja": entry.active_conflict_ja,
        "event_type": "hold",
        "stopped_on_day": 4,
        "rule_id": entry.verdict.rule_id,
    }


@pytest.mark.parametrize(("lang", "needle"), [("en", "intracranial hemorrhage"), ("ja", "頭蓋内出血")])
def test_the_discharge_summary_states_the_withhold(lang, needle):
    from clinosim.modules.document.narrative import _hospital_course as hc
    from tests.unit.modules.document.narrative.test_hospital_course_3246 import _ctx

    skips = [_withhold_skip("DVT", "深部静脈血栓症"), _withhold_skip("pulmonary embolism", "肺塞栓症")]
    sentence, fact = hc.withheld_anticoagulation_sentence(_ctx(lang, safety_skips=skips))
    assert needle in sentence and fact == "ctx.safety_skips"
    assert sentence.count("ヘパリン" if lang == "ja" else "Heparin") == 1, "one statement per drug"
    assert not sentence.startswith(("・", "-"))
    assert hc.withheld_anticoagulation_sentence(_ctx(lang)) == ("", "")
    other = dict(skips[0], rule_id="some-other-rule")
    assert hc.withheld_anticoagulation_sentence(_ctx(lang, safety_skips=[other])) == ("", "")
