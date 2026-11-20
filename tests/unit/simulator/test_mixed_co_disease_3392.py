"""Issue #3392: the co-disease of a mixed admission is coded, worked up and
treated, from the admission or (recognised late) from hospital day 1-3, and
resolves with treatment; the stay's own random stream is not read for it."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.order.engine import first_line_alternative_groups, place_admission_orders
from clinosim.simulator import run_forced
from clinosim.simulator.inpatient import _derive_final_diagnosis
from clinosim.simulator.mixed_condition import (
    CO_DISEASE_ID_INFIX,
    co_disease_course,
    co_disease_recognised_late,
    co_disease_recognition_day,
    merge_co_disease_orders,
    mixed_condition_rules,
)
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import Order, OrderType

pytestmark = pytest.mark.unit

_ADMISSION = datetime(2025, 3, 1, 9, 0)


def _place(disease_id: str, infix: str = "", country: str = "us") -> list[Order]:
    return place_admission_orders(
        load_disease_protocol(disease_id).model_dump(),
        "P-1",
        "ENC-1",
        _ADMISSION,
        country=country,
        rng=np.random.default_rng(1),
        id_infix=infix,
    )


def test_rules_are_consistent() -> None:
    rules = mixed_condition_rules()
    assert 0.0 < rules.delayed_recognition_probability < 1.0
    assert 1 <= rules.recognition_day_min <= rules.recognition_day_max
    assert "inflammation_level" in rules.recovered_axes


def test_recognition_day_follows_the_encounter_id_only() -> None:
    rules = mixed_condition_rules()
    ids = [f"ENC-{i}" for i in range(2000)]
    days = [co_disease_recognition_day(i) for i in ids]
    assert days == [co_disease_recognition_day(i) for i in ids]
    late = [d for d in days if d]
    assert all(rules.recognition_day_min <= d <= rules.recognition_day_max for d in late)
    assert {d for d in late} == set(range(rules.recognition_day_min, rules.recognition_day_max + 1))
    assert all((d > 0) == co_disease_recognised_late(i) for d, i in zip(days, ids, strict=True))
    assert abs(len(late) / len(ids) - rules.delayed_recognition_probability) < 0.05


def test_infix_keeps_the_default_ids_and_makes_the_co_disease_ids_unique() -> None:
    plain = _place("bacterial_pneumonia")
    assert plain == _place("bacterial_pneumonia", infix="")
    co = _place("bacterial_pneumonia", infix=CO_DISEASE_ID_INFIX)
    primary = _place("hip_fracture")
    assert len({o.order_id for o in primary + co}) == len(primary) + len(co)
    assert all(f"-ADM-{CO_DISEASE_ID_INFIX}" in o.order_id for o in co)
    # same orders, only the ids differ
    assert [o.display_name for o in co] == [o.display_name for o in plain]
    assert first_line_alternative_groups(load_disease_protocol("bacterial_pneumonia"), "ENC-1", "us", "C") == ()


def test_merge_leaves_out_what_the_stay_already_has() -> None:
    primary = _place("hip_fracture")
    co = _place("bacterial_pneumonia", infix=CO_DISEASE_ID_INFIX)
    merged = merge_co_disease_orders(primary, co, [])
    have_labs = {o.display_name for o in primary if o.order_type == OrderType.LAB}
    assert not [o for o in merged if o.order_type == OrderType.LAB and o.display_name in have_labs]
    assert not [o for o in merged if o.display_name.startswith(("IV_fluid:", "DVT_prophylaxis:"))]
    names = {o.display_name for o in merged}
    assert {"Ceftriaxone", "Azithromycin"} <= names
    assert any(n.startswith("O2:") for n in names)
    assert len({o.order_id for o in primary + merged}) == len(primary) + len(merged)


def test_co_disease_course_returns_the_onset_axes_over_the_recovery_days() -> None:
    protocol = load_disease_protocol("bacterial_pneumonia")
    course = co_disease_course(protocol, 2, [])
    rules = mixed_condition_rules()
    onset = protocol.initial_state_impact["moderate"]["inflammation_level"]
    assert course.changes_on(1) == {}
    total = sum(course.changes_on(d).get("inflammation_level", 0.0) for d in range(0, 30))
    assert total == pytest.approx(-onset)
    assert course.changes_on(2 + rules.recovery_days - 1) and not course.changes_on(2 + rules.recovery_days)


def test_deferred_orders_are_due_on_the_treatment_day_only() -> None:
    order = Order(order_id="O-1")
    late = co_disease_course(load_disease_protocol("bacterial_pneumonia"), 2, [order])
    assert [late.orders_due(d) for d in range(4)] == [[], [], [order], []]
    assert co_disease_course(load_disease_protocol("bacterial_pneumonia"), 0, []).orders_due(0) == []


def _derive(secondary: str | None, late: bool, rng: np.random.Generator):
    from clinosim.modules.diagnosis.engine import initialize_differential

    protocol = load_disease_protocol("hip_fracture")
    patient = SimpleNamespace(sex="F", age=80, chronic_conditions=[], patient_id="P-1")
    sec = load_disease_protocol(secondary) if secondary else None
    return _derive_final_diagnosis(
        differential=initialize_differential("hip_fracture", 80, protocol_diagnostic=protocol.diagnostic),
        protocol=protocol,
        secondary_protocol=sec,
        secondary_disease_id=secondary,
        patient=patient,  # type: ignore[arg-type]
        config=SimpleNamespace(country="US"),  # type: ignore[arg-type]
        rng=rng,  # type: ignore[arg-type]
        vitals=[],
        mars=[],
        lab_results=[],
        encounter_id="ENC-9",
        secondary_recognised_late=late,
    )[0]


@pytest.mark.parametrize("late", [False, True])
def test_the_co_disease_is_coded_and_missed_only_when_recognised_late(late: bool) -> None:
    dx = _derive("bacterial_pneumonia", late, np.random.default_rng(0))
    assert "J18.9" in dx.secondary_diagnosis_codes
    assert dx.missed_diagnoses == (["bacterial_pneumonia"] if late else [])


def test_the_stay_stream_advances_exactly_as_before() -> None:
    a, b = np.random.default_rng(5), np.random.default_rng(5)
    _derive("bacterial_pneumonia", True, a)
    b.random()
    assert a.random() == b.random()
    c, d = np.random.default_rng(5), np.random.default_rng(5)
    _derive(None, False, c)
    assert c.random() == d.random()
    assert _derive(None, False, np.random.default_rng(0)).secondary_diagnosis_codes == []


def _forced(country: str, seed: int, secondary: str | None = "bacterial_pneumonia"):
    d = run_forced(
        ForcedScenario(disease_id="hip_fracture", count=1, severity="moderate", secondary_disease_id=secondary),
        SimulatorConfig(random_seed=seed, country=country),
    )
    return d.patients[0]


@pytest.mark.parametrize(("country", "antibiotic"), [("US", "ceftriaxone"), ("JP", "ampicillin")])
def test_mixed_hip_fracture_and_pneumonia_codes_and_treats_the_pneumonia(country: str, antibiotic: str) -> None:
    for seed in range(1, 12):
        rec = _forced(country, seed)
        enc = rec.encounters[0]
        late = co_disease_recognition_day(enc.encounter_id)
        assert any(c.startswith("J1") for c in rec.clinical_diagnosis.secondary_diagnosis_codes)
        abx = [o for o in rec.orders if antibiotic in (o.display_name or "").lower()]
        assert abx, f"no {antibiotic} order (seed {seed})"
        first_day = min((o.ordered_datetime.date() - enc.admission_datetime.date()).days for o in abx)
        assert first_day == late
        assert len({o.order_id for o in rec.orders}) == len(rec.orders)
        assert rec.condition_event.ground_truth_diseases == ["hip_fracture", "bacterial_pneumonia"]
        assert any(m for m in rec.medication_administrations if antibiotic in (m.drug_name or "").lower())


def test_the_inflammation_of_the_treated_co_disease_resolves() -> None:
    rec = _forced("US", 3)
    crp = [float(x.value) for x in rec.lab_results if x.lab_name == "CRP" and x.value is not None]
    assert len(crp) >= 3
    assert crp[-1] < 0.25 * max(crp)


def test_a_stay_with_one_disease_has_no_co_disease_orders() -> None:
    rec = _forced("US", 3, secondary=None)
    assert not [o for o in rec.orders if f"-ADM-{CO_DISEASE_ID_INFIX}" in o.order_id]
    assert rec.clinical_diagnosis.secondary_diagnosis_codes == []
