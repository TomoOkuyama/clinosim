"""Issue #3247 (a): the progress-note plan lists the day's medications by
clinical priority, separates started / stopped / one-time doses from the
continued ones, and names every drug (or counts the rest). Also the
single-dose part of Issue #3260: newborn vitamin K is given, not continued."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers._composers import compose_progress_plan_from_state


def _ctx(lang: str, meds: list[dict], day: int = 1, **kw) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        day_index=day,
        medications=meds,
        procedures=[],
        orders=kw.get("orders", []),
        encounter=kw.get("encounter"),
        authored_datetime=kw.get("as_of"),
    )


def _med(name: str, day: int, **kw) -> dict:
    return {"drug_name": name, "day": day, "status": "given", **kw}


def test_vasopressor_and_antimicrobial_lead_a_long_list() -> None:
    chronic = ["Clopidogrel", "Atorvastatin", "Hydrochlorothiazide", "Amlodipine", "Vitamin D", "Candesartan"]
    meds = [_med(n, 1) for n in chronic] + [_med("Meropenem", 1, route="IV"), _med("Norepinephrine", 1, route="IV")]
    plan = compose_progress_plan_from_state(_ctx("en", meds))
    assert "Norepinephrine" in plan and "Meropenem" in plan
    assert plan.index("Norepinephrine") < plan.index("Meropenem") < plan.index("Clopidogrel")
    for name in chronic:
        assert name in plan


def test_drugs_beyond_the_cap_are_counted() -> None:
    from clinosim.modules.document.narrative._medication_plan import medication_plan_rules

    cap = medication_plan_rules().max_listed
    names = ["Clopidogrel", "Atorvastatin", "Amlodipine", "Candesartan", "Furosemide", "Digoxin", "Aspirin"]
    names += ["Pantoprazole", "Metformin", "Spironolactone"]
    plan = compose_progress_plan_from_state(_ctx("en", [_med(n, 1) for n in names]))
    assert f"(and {len(names) - cap} others)" in plan
    plan_ja = compose_progress_plan_from_state(_ctx("ja", [_med(n, 1) for n in names]))
    assert f"（他 {len(names) - cap} 剤）" in plan_ja


@pytest.mark.parametrize(("lang", "given", "cont"), [("en", "Given once:", "Continue"), ("ja", "単回投与:", "継続")])
def test_one_time_orders_are_given_not_continued(lang: str, given: str, cont: str) -> None:
    orders = [
        {"order_id": "O-CA", "order_type": "medication", "frequency": "once", "single_dose": True},
        {"order_id": "O-AM", "order_type": "medication", "frequency": "DAILY", "single_dose": False},
    ]
    meds = [
        _med("Amlodipine", 0, order_id="O-AM"),
        _med("Amlodipine", 1, order_id="O-AM"),
        _med("Calcium Gluconate 1 g IV", 1, order_id="O-CA", route="IV"),
    ]
    plan = compose_progress_plan_from_state(_ctx(lang, meds, orders=orders))
    given_part = plan[plan.index(given) :]
    assert ("Calcium Gluconate" if lang == "en" else "グルコン酸カルシウム") in given_part
    assert cont in plan[: plan.index(given)]
    assert ("Calcium" if lang == "en" else "グルコン酸") not in plan[: plan.index(given)]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_newborn_vitamin_k_is_given_once(lang: str) -> None:
    """Issue #3260: the birth dose (frequency "once", not flagged single_dose)."""
    name = "Vitamin K1 (phytonadione) 1 mg IM" if lang == "en" else "ケイツーシロップ (メナテトレノン 2 mg 経口)"
    orders = [{"order_id": "O-VK", "order_type": "medication", "frequency": "once", "single_dose": False}]
    plan = compose_progress_plan_from_state(_ctx(lang, [_med(name, 1, order_id="O-VK")], orders=orders))
    assert "Continue" not in plan and "継続" not in plan
    assert plan.startswith("Given once:" if lang == "en" else "単回投与:")


def test_an_unused_as_needed_drug_is_not_stopped() -> None:
    orders = [{"order_id": "O-APAP", "order_type": "medication", "frequency": "Q6H PRN", "single_dose": False}]
    meds = [*(_med("Amlodipine", d) for d in range(4)), _med("Acetaminophen 1000mg IV PRN", 1, order_id="O-APAP")]
    plan = compose_progress_plan_from_state(_ctx("en", meds, day=2, orders=orders))
    assert plan == "Continue current medications: Amlodipine."
    meds.append(_med("Acetaminophen 1000mg IV PRN", 3, order_id="O-APAP"))
    plan = compose_progress_plan_from_state(_ctx("en", meds, day=3, orders=orders))
    assert "Started" not in plan and "Acetaminophen" in plan


def test_started_and_stopped_against_the_previous_day() -> None:
    meds = [
        *(_med("Amlodipine", d) for d in range(5)),
        *(_med("Piperacillin/Tazobactam", d, route="IV") for d in (0, 1, 2)),
        *(_med("Meropenem", d, route="IV") for d in (3, 4)),
    ]
    day3 = compose_progress_plan_from_state(_ctx("en", meds, day=3))
    assert "Started: Meropenem." in day3
    assert "Stopped: Piperacillin/Tazobactam." in day3
    assert "Continue current medications: Amlodipine." in day3
    day4 = compose_progress_plan_from_state(_ctx("en", meds, day=4))
    assert "Continue current medications: Meropenem, Amlodipine." in day4
    assert "Piperacillin" not in day4 and "Started" not in day4
    ja = compose_progress_plan_from_state(_ctx("ja", meds, day=3))
    assert "開始: メロペネム。" in ja and "中止: " in ja


def test_admission_day_drugs_are_not_started_on_the_first_note() -> None:
    meds = [_med("Ceftriaxone", 0, route="IV"), _med("Ceftriaxone", 1, route="IV")]
    plan = compose_progress_plan_from_state(_ctx("en", meds, day=1))
    assert plan == "Continue current medications: Ceftriaxone."


def test_a_drug_given_every_other_day_is_not_stopped() -> None:
    meds = [*(_med("Amlodipine", d) for d in range(4)), _med("Vancomycin", 1, route="IV"), _med("Vancomycin", 3)]
    plan = compose_progress_plan_from_state(_ctx("en", meds, day=2))
    assert "Stopped" not in plan
    assert "Vancomycin" in plan


def test_the_note_lists_what_its_writer_knew() -> None:
    """With an authored time, the note covers the doses of the preceding
    window (since the previous day's note): a drug first given after the
    note is started in the next one, and a one-time dose given the evening
    before is in the morning note."""
    adm = datetime(2026, 5, 10, 6, 0)
    enc = {"admission_datetime": adm.isoformat()}
    orders = [{"order_id": "O-PAT", "order_type": "medication", "frequency": "once", "single_dose": True}]

    def at(name: str, when: datetime, **kw) -> dict:
        return {"drug_name": name, "scheduled_datetime": when.isoformat(), "status": "given", **kw}

    meds = [
        *(at("Amlodipine", datetime(2026, 5, d, 8, 0)) for d in range(10, 15)),
        at("Meropenem", datetime(2026, 5, 12, 16, 0), route="IV"),
        at("Meropenem", datetime(2026, 5, 13, 0, 0), route="IV"),
        at("Meropenem", datetime(2026, 5, 13, 16, 0), route="IV"),
        at("Patiromer 8.4 g PO", datetime(2026, 5, 11, 19, 0), order_id="O-PAT"),
    ]
    note_d2 = compose_progress_plan_from_state(
        _ctx("en", meds, day=2, encounter=enc, orders=orders, as_of=datetime(2026, 5, 12, 6, 0))
    )
    assert "Meropenem" not in note_d2
    assert "Given once: Patiromer" in note_d2
    note_d3 = compose_progress_plan_from_state(
        _ctx("en", meds, day=3, encounter=enc, orders=orders, as_of=datetime(2026, 5, 13, 6, 0))
    )
    assert "Started: Meropenem." in note_d3
    assert "Patiromer" not in note_d3


def test_the_admission_plan_ranks_its_initial_medications() -> None:
    from clinosim.modules.document.narrative._medication_plan import ranked_medication_names

    meds = [_med(n, 0) for n in ("Atorvastatin", "Amlodipine", "Ceftriaxone", "Norepinephrine", "Enoxaparin")]
    names = ranked_medication_names(_ctx("en", meds, day=0), day=0)
    assert names == ["Norepinephrine", "Ceftriaxone", "Enoxaparin", "Atorvastatin", "Amlodipine"]


def test_a_loading_dose_then_maintenance_is_continued() -> None:
    orders = [
        {"order_id": "O-LOAD", "order_type": "medication", "frequency": "once", "single_dose": True},
        {"order_id": "O-ASA", "order_type": "medication", "frequency": "DAILY", "single_dose": False},
    ]
    meds = [
        _med("Heparin", 0),
        _med("Heparin", 1),
        _med("Aspirin 325mg", 0, order_id="O-LOAD"),
        _med("Aspirin 81mg", 1, order_id="O-ASA"),
    ]
    plan = compose_progress_plan_from_state(_ctx("en", meds, day=1, orders=orders))
    assert plan == "Continue current medications: Heparin, Aspirin 81mg."


def test_a_daily_dose_given_around_the_note_time_is_not_restarted() -> None:
    """A daily dose given a few minutes after one note and before the next
    leaves the period between them empty; the drug is still continued."""
    adm = datetime(2025, 12, 19, 8, 19)
    enc = {"admission_datetime": adm.isoformat()}

    def at(when: datetime) -> dict:
        return {"drug_name": "Lansoprazole", "actual_datetime": when.isoformat(), "status": "given"}

    meds = [at(datetime(2025, 12, 19, 9, 16)), at(datetime(2025, 12, 20, 8, 10))]
    meds += [at(datetime(2025, 12, 21, 8, 22)), at(datetime(2025, 12, 22, 8, 5))]
    plan = compose_progress_plan_from_state(_ctx("en", meds, day=3, encounter=enc, as_of=datetime(2025, 12, 22, 8, 19)))
    assert plan == "Continue current medications: Lansoprazole."
