"""Issue #3924: chronic maintenance drugs of ``discharge_oral`` are written with the chronic supply.

The default supply of a ``discharge_oral`` item is 7 days, which the carry-forward of
``_deactivate_to_layer1`` treats as a finite course. A heart-failure ACE inhibitor or
beta-blocker left at the default was therefore dropped from the person's medication list,
and the home ARB it had replaced came back at the first follow-up visit.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_demographics
from clinosim.modules import drug_safety
from clinosim.modules.disease.protocol import load_all_disease_protocols, load_disease_protocol
from clinosim.modules.patient.activator import activate_patient
from clinosim.simulator.discharge_rx import build_discharge_rx
from clinosim.simulator.helpers import is_finite_course
from clinosim.types.patient import HomeMedication
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

# Classes whose discharge_oral entries are maintenance therapy: a supply left at the
# 7-day default is a defect, an explicit duration is the protocol's intention.
_MAINTENANCE_CLASSES = {
    "acei",
    "arb",
    "beta_blocker",
    "statin",
    "antiplatelet",
    "anticoagulant",
    "sglt2i",
    "diuretic.k_sparing",
    "vitamin_d_analogue",
}


def _drug_name(entry: dict) -> str:
    from clinosim.codes.drugs import resolve_drug

    if entry.get("drug_id"):
        return resolve_drug(entry["drug_id"]).names["en"]
    return str(entry.get("drug") or "")


def test_maintenance_discharge_oral_entries_declare_their_supply() -> None:
    offenders = []
    for disease_id, protocol in load_all_disease_protocols().items():
        block = protocol.drugs.get("discharge_oral")
        if not isinstance(block, dict):
            continue
        for country in ("japan", "us"):
            for entry in block.get(country) or []:
                if entry.get("duration_days") is not None:
                    continue
                name = _drug_name(entry)
                if set(drug_safety.resolve_classes(name) or ()) & _MAINTENANCE_CLASSES:
                    offenders.append(f"{disease_id}/{country}/{name}")
    assert offenders == []


@pytest.mark.parametrize(
    ("country", "drugs"), [("japan", {"Enalapril", "Carvedilol"}), ("us", {"Lisinopril", "Carvedilol"})]
)
def test_heart_failure_discharge_maintenance_drugs_have_28_day_supply(country: str, drugs: set[str]) -> None:
    protocol = load_disease_protocol("heart_failure_exacerbation")
    person = PersonRecord(
        person_id="P-3924",
        household_id="H",
        sex="M",
        age=70,
        date_of_birth=date(1955, 1, 1),
        chronic_conditions=["I10"],
    )
    patient = activate_patient(
        person, np.random.default_rng(0), load_demographics("JP" if country == "japan" else "US"), as_of_year=2025
    )
    rx = build_discharge_rx(
        patient=patient,
        disease_id="heart_failure_exacerbation",
        protocol=protocol,
        prescriber_id="md",
        admission_time=datetime(2026, 1, 5, 9, 0),
        country_key=country,
        encounter_id="enc-3924",
    )
    by_name = {it["drug_name"]: it for it in rx.items}
    for name in drugs:
        assert by_name[name]["duration_days"] == 28
        assert not is_finite_course(by_name[name])


def test_replaced_arb_does_not_return_after_the_ace_inhibitor_is_carried_forward() -> None:
    """The discharge reconciliation keeps the ACE inhibitor over the home ARB; the carried list
    keeps it too, so the re-activation at the next visit does not derive the ARB again."""
    protocol = load_disease_protocol("heart_failure_exacerbation")
    demo = load_demographics("JP")
    checked = 0
    for n in range(60):
        person = PersonRecord(
            person_id=f"P-3924-{n}",
            household_id="H",
            sex="F",
            age=72,
            date_of_birth=date(1953, 1, 1),
            chronic_conditions=["I10", "I50.9"],
        )
        patient = activate_patient(person, np.random.default_rng(n), demo, as_of_year=2025)
        if not any("arb" in (drug_safety.resolve_classes(m.drug_name) or ()) for m in patient.current_medications):
            continue
        rx = build_discharge_rx(
            patient=patient,
            disease_id="heart_failure_exacerbation",
            protocol=protocol,
            prescriber_id="md",
            admission_time=datetime(2026, 1, 5, 9, 0),
            country_key="japan",
            encounter_id=f"enc-3924-{n}",
        )
        person.current_medications = [
            HomeMedication(
                drug_name=it["drug_name"],
                route=it.get("route", ""),
                dose=it.get("dose", ""),
                frequency=it.get("frequency", ""),
            )
            for it in rx.items
            if not is_finite_course(it)
        ]
        later = activate_patient(person, np.random.default_rng(n), demo, as_of_year=2025)
        names = [m.drug_name for m in later.current_medications]
        assert "Enalapril" in names
        assert not any("arb" in (drug_safety.resolve_classes(x) or ()) for x in names), names
        checked += 1
    assert checked > 0
