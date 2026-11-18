"""ED imaging honours ``countries`` and ``abnormal_rate_by_severity`` (Issue #3294).

The ED imaging step used to read only ``test`` and ``probability`` from each
workup imaging entry: a study listed for one country was ordered in every
country and every study read normal. The order now carries the entry's
abnormal rate to the imaging enricher, which reads the report with the visit
condition's templates; the country filter follows the draw so the visit's
random stream is consumed as before.
"""

from __future__ import annotations

import copy
from datetime import datetime

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import OrderType

pytestmark = pytest.mark.unit

_VISIT = datetime(2026, 1, 18, 14)


def _patient(seed: int, age: int = 40):
    rng = determinism.default_rng(seed)
    person = PersonRecord(
        person_id=f"T-{seed}",
        household_id="H",
        age=age,
        sex="F",
        date_of_birth=datetime(2026 - age, 1, 1).date(),
    )
    return activate_patient(person, rng, load_demographics("US"))


@pytest.fixture(autouse=True)
def _patched_protocol(monkeypatch):
    """``_simulate_ed_visit`` loads the protocol by name; serve the test's
    variant of it for that name."""
    import clinosim.modules.encounter.protocol as protocol

    real = protocol.load_encounter_condition
    served: dict[str, dict] = {}
    monkeypatch.setattr(protocol, "load_encounter_condition", lambda name: served.get(name) or real(name))
    return served


@pytest.fixture
def serve(_patched_protocol):
    return lambda cond: _patched_protocol.__setitem__(cond["name"], cond)


def _visit(condition: dict, seed: int, country: str = "US", config=None):
    roster = generate_roster("medium", country, determinism.default_rng(7))
    return _simulate_ed_visit(
        _patient(seed),
        condition,
        _VISIT,
        roster,
        determinism.default_rng(1000 + seed),
        country=country,
        config=config,
        force_severity="moderate",
    )


def _condition(name: str, imaging: list[dict]) -> dict:
    cond = copy.deepcopy(load_encounter_condition(name))
    cond["workup"]["imaging"] = imaging
    return {"name": name, **cond}


def _studies(record) -> list[str]:
    return [o.display_name for o in record.orders if o.order_type == OrderType.IMAGING]


@pytest.mark.parametrize("country,expected", [("US", []), ("JP", ["Wrist_Xray_AP_Lateral"])])
def test_a_study_listed_for_one_country_is_not_ordered_in_another(serve, country: str, expected: list[str]) -> None:
    cond = _condition("wrist_fracture", [{"test": "Wrist_Xray_AP_Lateral", "probability": 1.0, "countries": ["JP"]}])
    serve(cond)
    assert _studies(_visit(cond, 1, country)) == expected


def test_the_country_filter_leaves_the_visit_stream_unchanged(serve) -> None:
    plain = _condition("wrist_fracture", [{"test": "Wrist_Xray_AP_Lateral", "probability": 1.0}])
    listed = _condition("wrist_fracture", [{"test": "Wrist_Xray_AP_Lateral", "probability": 1.0, "countries": ["JP"]}])

    def others(rec):
        return [(o.display_name, o.ordered_datetime) for o in rec.orders if o.order_type != OrderType.IMAGING]

    serve(plain)
    first = others(_visit(plain, 2))
    serve(listed)
    assert first == others(_visit(listed, 2))


def test_the_order_carries_the_abnormal_rate(serve) -> None:
    rate = {"any": 0.25, "severe": 0.5}
    cond = _condition("wrist_fracture", [{"test": "Wrist_Xray_AP_Lateral", "probability": 1.0, "abnormal_rate_by_severity": rate}])
    serve(cond)
    [order] = [o for o in _visit(cond, 3).orders if o.order_type == OrderType.IMAGING]
    assert order.imaging_spec_meta["abnormal_rate_by_severity"] == rate


def _report(serve, name: str, test: str, seed: int, rate: dict[str, float]):
    cond = _condition(name, [{"test": test, "probability": 1.0, "abnormal_rate_by_severity": rate}])
    serve(cond)
    from clinosim.simulator.enrichers import register_builtin_enrichers

    register_builtin_enrichers()
    cfg = SimulatorConfig(country="US", random_seed=42)
    record = _visit(cond, seed, config=cfg)
    [study] = record.extensions["imaging"]
    return study.report


def test_a_fracture_visit_reads_the_wrist_film_abnormal(serve) -> None:
    report = _report(serve, "wrist_fracture", "Wrist_Xray_AP_Lateral", 4, {"any": 1.0})
    assert "fracture" in report.impression_text.lower()
    assert "No acute abnormal" not in report.findings_text


def test_a_zero_rate_reads_normal(serve) -> None:
    report = _report(serve, "wrist_fracture", "Wrist_Xray_AP_Lateral", 4, {"any": 0.0})
    assert report.impression_text == "No acute fracture."


def test_the_authored_rates_follow_the_visit_diagnosis() -> None:
    wrist = load_encounter_condition("wrist_fracture")["workup"]["imaging"]
    assert wrist[0]["abnormal_rate_by_severity"] == {"any": 1.0}
    shoulder = {s["test"]: s for s in load_encounter_condition("shoulder_dislocation")["workup"]["imaging"]}
    assert shoulder["Shoulder_Xray_AP_Lateral"]["abnormal_rate_by_severity"] == {"any": 1.0}
    assert shoulder["Shoulder_Xray_Post_Reduction"]["abnormal_rate_by_severity"] == {"any": 0.0}
