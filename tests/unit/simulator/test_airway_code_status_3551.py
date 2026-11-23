"""Intubation is reconciled with the code status (Issue #3551)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.code_status.engine import (
    airway_declined,
    airway_declined_probability,
    assign_tier,
    load_reference,
)
from clinosim.modules.code_status.enricher import enrich_code_status
from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import build_pn_consent
from clinosim.simulator import daily_loop as dl
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit

_DNR = next(t["snomed"] for t in load_reference()["tiers"] if t["key"] == "dnr")
_DECLINING = {t["key"] for t in load_reference()["tiers"] if t.get("declines_intubation")}


def test_declining_tiers_are_dnr_dni_and_comfort() -> None:
    assert _DECLINING == {"dnr_dni", "comfort"}


def test_declined_airway_draws_only_declining_tiers_and_intubated_only_the_others() -> None:
    for s in range(300):
        for age, ctx in ((80, "icu"), (30, "routine"), (90, "terminal")):
            declined = assign_tier(age, ctx, "US", np.random.default_rng(s), airway="declined")
            intubated = assign_tier(age, ctx, "JP", np.random.default_rng(s), airway="intubated")
            assert declined["key"] in _DECLINING
            assert intubated["key"] not in _DECLINING


def test_unrestricted_draw_is_unchanged() -> None:
    a = assign_tier(80, "terminal", "US", np.random.default_rng(5))
    b = assign_tier(80, "terminal", "US", np.random.default_rng(5), airway="")
    assert a == b


def test_airway_declined_is_deterministic_and_rate_matches_weights() -> None:
    assert airway_declined(85, "US", "ENC-1") == airway_declined(85, "US", "ENC-1")
    p = airway_declined_probability(85, "US")
    assert p == pytest.approx(0.30)
    n = sum(airway_declined(85, "US", f"ENC-{i}") for i in range(2000))
    assert abs(n / 2000 - p) < 0.04
    assert airway_declined_probability(85, "XX") == 0.0


def _stay(encounter_id: str, age: int = 85):
    return SimpleNamespace(patient=SimpleNamespace(age=age, patient_id="P"), country="US", encounter_id=encounter_id)


def test_airway_threshold_never_intubates_a_patient_who_declined(monkeypatch) -> None:
    monkeypatch.setattr(dl, "airway_escalation_needed", lambda state: True)
    monkeypatch.setattr(dl, "icu_escalation_needed", lambda state: False)
    declined = intubated = 0
    for i in range(200):
        stay = _stay(f"ENC-{i}")
        run = SimpleNamespace(
            intubated=False,
            airway_declined=False,
            intubated_day=None,
            state=PhysiologicalState(),
            escalation_procedures=[],
            oxygen=SimpleNamespace(start_ventilation=lambda t: None),
        )
        stay.admission_time = datetime(2026, 3, 1, 9, 0)
        stay.attending_id = "D1"
        dl._escalate_on_arrival(stay, run)
        if airway_declined(85, "US", stay.encounter_id):
            declined += 1
            assert run.airway_declined and not run.intubated and not run.escalation_procedures
        else:
            intubated += 1
            assert run.intubated and not run.airway_declined and len(run.escalation_procedures) == 1
    assert declined and intubated


def _rec(eid: str, *, declined: bool = False, intubation: bool = False) -> dict:
    return {
        "patient": {"patient_id": "P", "age": 85},
        "encounters": [{"encounter_id": eid, "encounter_type": "inpatient"}],
        "deceased": False,
        "icu_transferred": True,
        "airway_declined": declined,
        "procedures": [{"procedure_type": "intubation"}] if intubation else [],
    }


def test_enricher_keeps_the_airway_decision() -> None:
    recs = [_rec(f"E{i}", declined=True) for i in range(40)] + [_rec(f"F{i}", intubation=True) for i in range(120)]
    ctx = SimpleNamespace(config=SimpleNamespace(country="US"), master_seed=42, records=recs)
    enrich_code_status(ctx)
    assert all(r["code_status"] == _DNR for r in recs[:40])  # declining tiers share the not-for-resuscitation code
    # An intubated stay samples only full code / dnr, so the share of non-DNR is far above the unrestricted one.
    full = sum(r["code_status"] != _DNR for r in recs[40:])
    assert full / 120 > 0.5


def _consent(lang: str, ptype: str, code_status: str) -> str:
    ctx = NarrativeContext(
        patient=SimpleNamespace(patient_id="p", sex="M", chronic_conditions=[]),
        encounter=SimpleNamespace(encounter_id="e", encounter_type=SimpleNamespace(value="inpatient"), priority=""),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=3,
        los_days=7,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[{"procedure_id": "P1", "procedure_type": ptype, "start_datetime": "2026-03-23T15:17:00"}],
        prior_procedures=[],
        allergies=[],
        document_type=DocumentType.PROCEDURE_NOTE,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        related_procedure_id="P1",
        code_status=code_status,
    )
    return build_pn_consent(None, ctx)[0]


@pytest.mark.parametrize(("lang", "needle"), [("en", "time-limited trial"), ("ja", "タイムリミテッド・トライアル")])
def test_dnr_intubation_note_states_the_status(lang: str, needle: str) -> None:
    assert needle in _consent(lang, "intubation", _DNR)
    assert needle not in _consent(lang, "intubation", "304252001")
    assert needle not in _consent(lang, "central_line", _DNR)


@pytest.mark.parametrize(("lang", "needle"), [("en", "time-limited trial"), ("ja", "タイムリミテッド・トライアル")])
def test_first_progress_note_after_a_dnr_intubation_states_the_status(lang: str, needle: str) -> None:
    from datetime import datetime

    from clinosim.modules.document.narrative.renderers._composers import compose_progress_intubation_status_line

    def line(code: str, authored: datetime) -> str:
        ctx = SimpleNamespace(
            target_lang=lang,
            code_status=code,
            authored_datetime=authored,
            procedures=[{"procedure_type": "intubation", "start_datetime": "2026-03-02T10:00:00"}],
        )
        return compose_progress_intubation_status_line(ctx)

    assert needle in line(_DNR, datetime(2026, 3, 2, 12, 0))
    assert line("304252001", datetime(2026, 3, 2, 12, 0)) == ""
    assert line(_DNR, datetime(2026, 3, 9, 12, 0)) == ""  # a later note, outside the period
    assert line(_DNR, datetime(2026, 3, 2, 9, 0)) == ""  # before the intubation
