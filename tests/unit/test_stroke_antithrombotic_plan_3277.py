"""Issue #3277: antithrombotic therapy of a stroke admission.

Most acute ischemic stroke admissions received no antiplatelet or therapeutic
anticoagulant during the stay, and the discharge prescription put every
antiplatelet and an anticoagulant on top of each other. The protocol's
``antithrombotic_plan`` (``simulator/antithrombotic_plan.py``) now starts aspirin
within 24-48 h (AHA/ASA 2019 early management 3.9), the anticoagulant of a
patient with an indication on a severity-dependent day (6.6.2), short-term DAPT
for a minor stroke, and gives the discharge prescription one regimen: the
anticoagulant for an indication, otherwise aspirin; maintenance doses only.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.disease.protocol import DiseaseProtocol, load_disease_protocol
from clinosim.simulator.antithrombotic_plan import discharge_specs, steps_for_day
from clinosim.simulator.discharge_rx import build_discharge_rx

pytestmark = pytest.mark.unit

_ANTICOAGULANTS = ("Edoxaban", "Warfarin", "Apixaban")
_ANTIPLATELETS = ("Aspirin", "Clopidogrel")


def _protocol(af_implied: bool) -> DiseaseProtocol:
    protocol = load_disease_protocol("cerebral_infarction")
    return protocol if af_implied else protocol.model_copy(update={"implied_chronic_codes": ["I10", "E78"]})


def _steps(patient, protocol, *, severity="moderate", country="us", day, running=(), hemorrhage=False):
    return steps_for_day(
        patient,
        protocol,
        severity=severity,
        country_key=country,
        encounter_id="ENC-1",
        day=day,
        is_running=lambda drug: drug in running,
        hemorrhage=hemorrhage,
    )


def _drugs(steps, action):
    return [s.spec["drug_id"] for s in steps if s.action == action]


@pytest.mark.parametrize("country", ["us", "japan"])
def test_aspirin_is_started_within_24_to_48_hours_without_an_anticoagulant_indication(patient_factory, country):
    protocol = _protocol(af_implied=False)
    patient = patient_factory()
    assert _drugs(_steps(patient, protocol, day=0, country=country), "start") == []
    day1 = _steps(patient, protocol, day=1, country=country)
    assert _drugs(day1, "start") == ["aspirin"]  # 24-48 h after the admission day
    assert "loading, then" in day1[0].spec["dose"]  # 160-300 mg load, then the maintenance dose
    assert _steps(patient, protocol, day=2, country=country) == []


def test_minor_stroke_gets_short_term_dapt_with_a_defined_duration(patient_factory):
    protocol = _protocol(af_implied=False)
    steps = _steps(patient_factory(), protocol, severity="mild", day=0)
    assert _drugs(steps, "start") == ["aspirin", "clopidogrel"]
    clopidogrel = next(s.spec for s in steps if s.spec["drug_id"] == "clopidogrel")
    assert clopidogrel["duration_days"] == protocol.antithrombotic_plan.dapt_days == 21


@pytest.mark.parametrize(
    ("country", "severity", "day"),
    [("japan", "moderate", 3), ("japan", "severe", 4), ("us", "moderate", 7), ("us", "severe", 14)],
)
def test_anticoagulant_starts_on_the_severity_day_and_replaces_the_aspirin_bridge(
    patient_factory, country, severity, day
):
    protocol = _protocol(af_implied=True)  # every stroke patient carries AF (implied I48)
    patient = patient_factory()
    kwargs = {"country": country, "severity": severity}
    assert _drugs(_steps(patient, protocol, day=1, **kwargs), "start") == ["aspirin"]
    for d in range(2, day):
        assert _steps(patient, protocol, day=d, **kwargs) == []
    on_day = _steps(patient, protocol, day=day, running=("aspirin",), **kwargs)
    assert _drugs(on_day, "stop") == ["aspirin"]
    started = _drugs(on_day, "start")
    assert len(started) == 1 and started[0] in {"edoxaban", "apixaban", "warfarin"}


def test_anticoagulant_window_is_inside_the_guideline_range(patient_factory):
    """AHA/ASA 2019 6.6.2 rec 1: initiate oral anticoagulation 4 to 14 days after onset (US)."""
    plan = load_disease_protocol("cerebral_infarction").antithrombotic_plan
    assert all(4 <= d <= 14 for d in plan.by_country["us"].anticoagulant_start_day.values())
    assert all(d <= 4 for d in plan.by_country["japan"].anticoagulant_start_day.values())


def test_a_home_anticoagulant_continues_and_nothing_is_added(patient_factory):
    protocol = _protocol(af_implied=False)
    patient = patient_factory(current_meds=["Warfarin 3mg"])
    for day in range(0, 8):
        assert _steps(patient, protocol, day=day) == []


def test_hemorrhagic_transformation_stops_running_agents_and_starts_none(patient_factory):
    protocol = _protocol(af_implied=False)
    steps = _steps(patient_factory(), protocol, day=1, running=("aspirin",), hemorrhage=True)
    assert [(s.action, s.spec["drug_id"]) for s in steps] == [("stop", "aspirin")]


def test_a_protocol_without_a_plan_has_no_steps(patient_factory):
    protocol = load_disease_protocol("hemorrhagic_stroke")
    assert protocol.antithrombotic_plan is None
    assert _steps(patient_factory(), protocol, day=1) == []


def _items(patient, protocol, country, severity="moderate", seed=0):
    rx = build_discharge_rx(
        patient,
        "cerebral_infarction",
        protocol,
        "PR-1",
        datetime(2026, 1, 1),
        encounter_id=f"ENC-{seed}",
        country_key=country,
        severity=severity,
    )
    return rx.items


def _names(items):
    return [i["drug_name"] for i in items]


@pytest.mark.parametrize("country", ["us", "japan"])
def test_discharge_with_an_indication_has_an_anticoagulant_and_no_antiplatelet(patient_factory, country):
    protocol = _protocol(af_implied=True)
    for seed in range(40):
        names = _names(_items(patient_factory(), protocol, country, seed=seed))
        assert sum(any(a in n for a in _ANTICOAGULANTS) for n in names) == 1, names
        assert not any(a in n for n in names for a in _ANTIPLATELETS), names


@pytest.mark.parametrize("country", ["us", "japan"])
def test_discharge_without_an_indication_has_aspirin_and_no_anticoagulant(patient_factory, country):
    protocol = _protocol(af_implied=False)
    items = _items(patient_factory(), protocol, country)
    names = _names(items)
    assert any("Aspirin" in n for n in names) and not any(a in n for n in names for a in _ANTICOAGULANTS)
    assert not any("Clopidogrel" in n for n in names)  # DAPT is for a minor stroke only
    aspirin = next(i for i in items if "Aspirin" in i["drug_name"])
    assert "loading" not in aspirin["dose"].lower()  # maintenance dose only
    assert aspirin["dose"] in {"81mg PO daily", "100mg PO daily"}


def test_discharge_after_a_minor_stroke_has_dapt_with_a_defined_clopidogrel_duration(patient_factory):
    items = _items(patient_factory(), _protocol(af_implied=False), "us", severity="mild")
    clopidogrel = next(i for i in items if "Clopidogrel" in i["drug_name"])
    assert clopidogrel["duration_days"] == 21
    assert "loading" not in clopidogrel["dose"].lower()


def test_no_discharge_item_carries_loading_dose_text(patient_factory):
    for af in (True, False):
        for country in ("us", "japan"):
            for item in _items(patient_factory(), _protocol(af), country):
                assert "loading" not in item["dose"].lower(), item


def test_the_in_stay_anticoagulant_is_the_discharge_anticoagulant(patient_factory):
    protocol = _protocol(af_implied=True)
    for seed in range(30):
        steps = steps_for_day(
            patient_factory(),
            protocol,
            severity="moderate",
            country_key="japan",
            encounter_id=f"ENC-{seed}",
            day=3,
            is_running=lambda _d: False,
            hemorrhage=False,
        )
        in_stay = _drugs(steps, "start")[0]
        discharged = discharge_specs(
            patient_factory(),
            protocol,
            "anticoagulation",
            severity="moderate",
            country_key="japan",
            encounter_id=f"ENC-{seed}",
            prescribed=[],
        )
        assert [s["drug_id"] for s in discharged] == [in_stay]


def test_the_stay_hospital_started_aspirin_is_not_carried_over_an_anticoagulant(patient_factory):
    """The aspirin bridge is in ``current_medications`` at discharge; it must not
    block (or join) the anticoagulant the plan prescribes."""
    protocol = _protocol(af_implied=True)
    patient = patient_factory(current_meds=["Aspirin 100mg"])
    names = _names(_items(patient, protocol, "japan"))
    assert any(a in n for n in names for a in _ANTICOAGULANTS)
    assert not any("Aspirin" in n for n in names)


def test_plan_is_validated_at_load():
    protocol = load_disease_protocol("cerebral_infarction")
    data = protocol.model_dump()
    data["antithrombotic_plan"]["dapt_severities"] = ["minor"]
    with pytest.raises(ValueError, match="not severities"):
        DiseaseProtocol(**data)
    data = protocol.model_dump()
    data["antithrombotic_plan"]["anticoagulant_block"] = "no_such_block"
    with pytest.raises(ValueError, match="not a drug block"):
        DiseaseProtocol(**data)


def test_no_discharge_rng_draw_for_the_plan_blocks(patient_factory):
    """An injected rng still works (test escape hatch) and the plan blocks read none."""
    protocol = _protocol(af_implied=True)
    rx = build_discharge_rx(
        patient_factory(),
        "cerebral_infarction",
        protocol,
        "PR-1",
        datetime(2026, 1, 1),
        np.random.default_rng(0),
        encounter_id="ENC-1",
        country_key="us",
        severity="moderate",
    )
    assert any("Apixaban" in n or "Warfarin" in n for n in _names(rx.items))


def _cohort(tmp_path, disease: str, country: str) -> list[dict]:
    import json
    import subprocess
    import sys

    out = tmp_path / f"{disease}_{country}"
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease", disease, "-n", "6", "-s", "11"]
        + ["--format", "cif", "-o", str(out), "--country", country],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode == 0, r.stderr
    return [json.loads(p.read_text()) for p in sorted((out / "cif" / "structural" / "patients").glob("*.json"))]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_simulated_ischemic_stroke_stays_get_aspirin_within_48_hours_and_an_anticoagulant_at_discharge(
    tmp_path, country
):
    for record in _cohort(tmp_path, "cerebral_infarction", country):
        enc = record["encounters"][0]
        admitted = datetime.fromisoformat(enc["admission_datetime"])
        given = [m for m in record["medication_administrations"] if m["status"] == "given"]
        antiplatelet = [m for m in given if "spirin" in m["drug_name"]]
        assert antiplatelet, "no aspirin given in the stay"
        first_h = (datetime.fromisoformat(min(m["actual_datetime"] for m in antiplatelet)) - admitted).total_seconds()
        assert 24 <= first_h / 3600 <= 48
        if record["deceased"]:
            continue
        names = [i["drug_name"] for i in record["discharge_prescription"]["items"]]
        assert sum(any(a in n for a in _ANTICOAGULANTS) for n in names) == 1
        assert not any(a in n for n in names for a in _ANTIPLATELETS)


def test_simulated_hemorrhagic_stroke_stays_get_no_antithrombotic(tmp_path):
    for record in _cohort(tmp_path, "hemorrhagic_stroke", "US"):
        given = [m["drug_name"] for m in record["medication_administrations"] if m["status"] == "given"]
        assert not any(a in n for n in given for a in (*_ANTIPLATELETS, *_ANTICOAGULANTS)), given
        rx = (record["discharge_prescription"] or {"items": []})["items"]
        names = [i["drug_name"] for i in rx]
        assert not any(a in n for n in names for a in (*_ANTIPLATELETS, *_ANTICOAGULANTS)), names
