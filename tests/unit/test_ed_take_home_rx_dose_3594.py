"""Every ED take-home prescription carries a dose or a sig (Issue #3594)."""

from __future__ import annotations

import copy

import pytest

from clinosim.countries import country_slot
from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,
    load_all_encounter_conditions,
    load_encounter_condition,
    prescription_dose,
)
from clinosim.modules.order.engine import parse_dose_string

pytestmark = pytest.mark.unit

_COUNTRIES = ("US", "JP")


def _entries():
    for cid, cond in sorted(load_all_encounter_conditions().items()):
        for spec in cond.get("discharge_prescriptions") or []:
            yield cid, spec


@pytest.mark.parametrize("country", _COUNTRIES)
def test_every_take_home_prescription_resolves_to_a_dose_or_a_sig(country: str) -> None:
    key = country_slot(country)
    missing = []
    for cid, spec in _entries():
        name = (spec.get("locale_name") or {}).get(key) or spec["drug"]
        if not prescription_dose(spec, name, key):
            missing.append(f"{cid}: {name}")
    assert not missing, f"take-home prescriptions with neither dose nor sig ({country}): {missing}"


def test_protocol_rejects_a_take_home_prescription_without_dose_or_sig() -> None:
    raw = copy.deepcopy(load_encounter_condition("viral_uri"))
    raw["discharge_prescriptions"] = [{"drug": "Dextromethorphan/Guaifenesin", "route": "PO"}]
    with pytest.raises(ValueError, match="no dose or sig"):
        EncounterConditionProtocol.model_validate(raw)


def test_locale_dose_overrides_the_strength_written_in_the_name() -> None:
    spec = {"drug": "X", "dose": "10mL", "locale_dose": {"jp": "15mg"}}
    assert prescription_dose(spec, "X", "us") == "10mL"
    assert prescription_dose(spec, "X", "jp") == "15mg"
    assert prescription_dose({"drug": "X"}, "X 15mg", "us") == "15mg"


@pytest.mark.parametrize(
    ("text", "quantity", "unit"),
    [("10mL", 10.0, "mL"), ("0.3mg", 0.3, "mg"), ("2 puffs", 2.0, "puff")],
)
def test_quantity_doses_parse_to_a_dose_quantity(text: str, quantity: float, unit: str) -> None:
    parsed = parse_dose_string(text)
    assert (parsed["dose_quantity"], parsed["dose_unit"]) == (quantity, unit)


def _mr(drug: str, dose: str, route: str, frequency: str, country: str) -> dict:
    from clinosim.modules.output.fhir_r4.medications.medications import _build_discharge_medication_request

    item = {"drug_name": drug, "dose": dose, "route": route, "frequency": frequency, "duration_days": 5}
    return _build_discharge_medication_request(
        item, "P-1", country, "ENC-1", "emergency", 1, "2024-06-01T10:00:00+00:00"
    )


@pytest.mark.parametrize("country", _COUNTRIES)
@pytest.mark.parametrize(
    ("drug", "dose", "route", "frequency", "quantity"),
    [
        ("Dextromethorphan/Guaifenesin", "10mL", "PO", "q6h PRN", True),
        ("Albuterol MDI", "2 puffs", "INH", "Q4-6H PRN", True),
        ("Epinephrine auto-injector", "0.3mg", "IM", "PRN emergency (max 2/day)", True),
        ("Ofloxacin ophthalmic drops", "1 drop in the affected eye", "topical", "qid", False),
        ("Silver sulfadiazine cream", "apply a thin layer to the affected area", "topical", "bid", False),
    ],
)
def test_take_home_medication_request_states_the_amount(
    drug: str, dose: str, route: str, frequency: str, quantity: bool, country: str
) -> None:
    dosage = _mr(drug, dose, route, frequency, country)["dosageInstruction"][0]
    assert dosage.get("text"), dosage
    assert bool(dosage.get("doseAndRate")) is quantity, dosage
    if country == "JP":
        assert not any(c.isascii() and c.isalpha() for c in dosage["text"].replace("mL", "").replace("mg", "")), dosage


def _items(country: str, age: int, condition: str = "viral_uri") -> dict[str, str]:
    import clinosim.modules.encounter.protocol as protocol_mod
    from tests.unit.test_ed_discharge_prescriptions_2155 import _all_certain, _visit

    cond = _all_certain(condition)
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(protocol_mod, "load_encounter_condition", lambda _cid: cond)
        record = _visit(cond, age=age, country=country)
    finally:
        mp.undo()
    rx = record.discharge_prescription
    return {i["drug_name"]: i["dose"] for i in rx.items} if rx else {}


def test_cough_syrup_dose_follows_country_and_age() -> None:
    assert _items("US", 40)["Dextromethorphan/Guaifenesin"] == "10mL"
    assert _items("JP", 40)["Dextromethorphan"] == "15mg"
    assert not any("Dextromethorphan" in d for d in _items("US", 8))


def test_take_home_items_carry_the_declared_dose() -> None:
    assert _items("US", 40, "asthma_attack_mild")["Albuterol MDI"] == "2 puffs"
    assert _items("US", 40, "eye_foreign_body")["Ofloxacin ophthalmic drops"] == "1 drop in the affected eye"
    assert _items("US", 40, "allergic_reaction_mild")["Epinephrine auto-injector"] == "0.3mg"
