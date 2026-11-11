"""Perinatal parameters and the validator LOS benchmarks are country data
read by country slot, not selected by country branches (Issue #3184;
docs/design-guides/country-profile-spec.md §7 step 3)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_perinatal_config

pytestmark = pytest.mark.unit


def test_postop_analgesic_is_perinatal_data() -> None:
    cfg = load_perinatal_config()["cesarean"]["postop_analgesic"]
    assert cfg["by_country"] == {"us": "ketorolac", "jp": "acetaminophen"}
    assert cfg["allergy_substitute"] == "acetaminophen"
    assert cfg["drugs"]["ketorolac"] == {
        "order_suffix": "CSKT",
        "name": "Ketorolac",
        "dose": 30.0,
        "unit": "mg",
        "route": "IV",
    }
    assert cfg["drugs"]["acetaminophen"] == {
        "order_suffix": "CSAM",
        "name": "Acetaminophen",
        "dose": 1000.0,
        "unit": "mg",
        "route": "IV",
    }


def test_delivery_for_a_country_without_a_profile_raises() -> None:
    from clinosim.modules.staff.engine import StaffRoster
    from clinosim.simulator.perinatal import simulate_delivery_encounter
    from clinosim.types.patient import PatientProfile

    with pytest.raises(KeyError):
        simulate_delivery_encounter(
            patient=PatientProfile(patient_id="POP-000003", sex="F", age=28),
            visit_date=datetime(2024, 7, 15, 10, 0),
            roster=StaffRoster(),
            rng=np.random.default_rng(42),
            country="FR",
            hospital_ops={},
        )


def test_los_benchmarks_are_reference_data() -> None:
    from clinosim.modules.validator.benchmarks import los_benchmarks

    assert los_benchmarks("US") == {
        "median_los": {"expected": 4.5, "range": [3, 7]},
        "mean_los": {"expected": 5, "range": [3, 8]},
    }
    assert los_benchmarks("japan") == {
        "median_los": {"expected": 14, "range": [10, 20]},
        "mean_los": {"expected": 15, "range": [10, 22]},
    }
    with pytest.raises(KeyError):
        los_benchmarks("FR")


def _cesarean_orders(country: str, patient_id: str, monkeypatch: pytest.MonkeyPatch, blocked: bool) -> tuple:
    import clinosim.simulator.perinatal as perinatal
    from clinosim.modules.staff.engine import StaffRoster
    from clinosim.types.patient import PatientProfile

    calls: list[tuple[str, str | None]] = []

    def fake_blocked(patient, drug_name, *, encounter_id, timestamp, substituted_with=None):  # type: ignore[no-untyped-def]
        calls.append((drug_name, substituted_with))
        return blocked and drug_name == "Ketorolac"

    monkeypatch.setattr(perinatal, "allergy_blocked", fake_blocked)
    records = perinatal.simulate_delivery_encounter(
        patient=PatientProfile(patient_id=patient_id, sex="F", age=28),
        visit_date=datetime(2024, 7, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(42),
        country=country,
        hospital_ops={},
    )
    return records[0].orders, calls


def test_us_allergy_substitutes_acetaminophen(monkeypatch: pytest.MonkeyPatch) -> None:
    orders, calls = _cesarean_orders("US", "POP-000005", monkeypatch, blocked=True)
    assert ("Ketorolac", "Acetaminophen") in calls
    acet = next(o for o in orders if o.display_name == "Acetaminophen")
    assert acet.order_id.endswith("-CSAM-01") and acet.dose_quantity == 1000.0
    assert not any(o.display_name == "Ketorolac" for o in orders)


def test_jp_takes_acetaminophen_without_an_allergy_check(monkeypatch: pytest.MonkeyPatch) -> None:
    orders, calls = _cesarean_orders("JP", "POP-000003", monkeypatch, blocked=True)
    assert not any(drug == "Ketorolac" for drug, _ in calls)
    assert any(o.display_name == "Acetaminophen" and o.order_id.endswith("-CSAM-01") for o in orders)
