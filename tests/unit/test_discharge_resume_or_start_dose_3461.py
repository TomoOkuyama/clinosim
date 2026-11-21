"""A discharge item states a dose: the home regimen continued, else a start dose
(Issues #3461, #3462).

A ``discharge_oral`` entry with ``home_dose: resume`` continues the patient's
home regimen of the drug (dose / route / frequency) when it has one, and
otherwise starts the entry's ``start_dose`` (a structured dose, or the
weight-based basal-insulin rule of ``insulin_initiation.yaml``).
"""

from __future__ import annotations

import re
from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.order.insulin_initiation import basal_insulin_start_units, insulin_initiation_rules
from clinosim.simulator.discharge_rx import build_discharge_rx
from clinosim.types.patient import HomeMedication

pytestmark = pytest.mark.unit

ADMISSION = datetime(2026, 1, 1, 10, 30)
_DOSE = re.compile(r"^\d+(?:\.\d+)?\s*(?:mcg|mg|U|units?)\b", re.IGNORECASE)


def _rx(patient, disease_id: str, country: str = "us", seed: int = 0):
    return build_discharge_rx(
        patient,
        disease_id,
        load_disease_protocol(disease_id),
        "PR-1",
        ADMISSION,
        np.random.default_rng(seed),
        encounter_id="ENC-1",
        country_key=country,
        discharge_time=datetime(2026, 1, 5, 12, 0),
    )


def _item(rx, key: str) -> dict:
    hits = [i for i in rx.items if key in i["drug_name"].lower().replace(" ", "_").replace("/", "_")]
    assert len(hits) == 1, [i["drug_name"] for i in rx.items]
    return hits[0]


@pytest.mark.parametrize("country", ["us", "japan"])
def test_asthma_controller_without_home_supply_gets_a_start_dose(patient_factory, country) -> None:
    item = _item(_rx(patient_factory(age=40), "asthma_exacerbation", country), "fluticasone")
    assert item["dose"] == "250mcg"
    assert item["route"] == "INH"
    assert item["frequency"] == "bid"
    assert not item.get("dose_en") and not item.get("dose_ja")


@pytest.mark.parametrize("country", ["us", "japan"])
def test_asthma_controller_continues_the_home_regimen(patient_factory, country) -> None:
    patient = patient_factory(age=40)
    patient.current_medications = [
        HomeMedication(drug_name="Fluticasone/Salmeterol", route="INH", dose="500mcg", frequency="bid")
    ]
    item = _item(_rx(patient, "asthma_exacerbation", country), "salmeterol")
    assert (item["dose"], item["route"], item["frequency"]) == ("500mcg", "INH", "bid")


def test_home_drug_without_a_recorded_dose_falls_back_to_the_start_dose(patient_factory) -> None:
    patient = patient_factory(age=40)
    patient.current_medications = [HomeMedication(drug_name="Fluticasone/Salmeterol", route="INH")]
    assert _item(_rx(patient, "asthma_exacerbation"), "salmeterol")["dose"] == "250mcg"


def test_child_asthma_entries_are_unchanged(patient_factory) -> None:
    item = _item(_rx(patient_factory(age=8), "asthma_exacerbation"), "fluticasone_propionate")
    assert (item["dose"], item["route"], item["frequency"]) == ("50mcg", "INH", "bid")


@pytest.mark.parametrize("country", ["us", "japan"])
def test_insulin_naive_dka_patient_gets_a_weight_based_basal_dose(patient_factory, country) -> None:
    patient = patient_factory(age=30)
    patient.weight_kg = 70.0
    item = _item(_rx(patient, "diabetic_ketoacidosis", country), "insulin_glargine")
    units = basal_insulin_start_units(70.0)
    assert item["dose"] == f"{units}U"
    assert (item["route"], item["frequency"]) == ("SC", "daily")
    assert not item.get("dose_en") and not item.get("dose_ja")
    assert "regimen" not in str(item).lower()


def test_basal_dose_follows_weight(patient_factory) -> None:
    light, heavy = patient_factory(age=30), patient_factory(age=30)
    light.weight_kg, heavy.weight_kg = 50.0, 100.0
    d_light = _item(_rx(light, "diabetic_ketoacidosis"), "insulin_glargine")["dose"]
    d_heavy = _item(_rx(heavy, "diabetic_ketoacidosis"), "insulin_glargine")["dose"]
    assert int(d_heavy.rstrip("U")) > int(d_light.rstrip("U"))


def test_dka_patient_with_home_insulin_keeps_the_home_dose(patient_factory) -> None:
    patient = patient_factory(age=30)
    patient.current_medications = [
        HomeMedication(drug_name="Insulin glargine", route="SC", dose="10U", frequency="daily")
    ]
    item = _item(_rx(patient, "diabetic_ketoacidosis"), "insulin_glargine")
    assert (item["dose"], item["route"], item["frequency"]) == ("10U", "SC", "daily")


def test_start_dose_rule_is_rounded_to_whole_units_and_sourced() -> None:
    rules = insulin_initiation_rules()
    assert rules.basal.units_per_kg > 0
    assert basal_insulin_start_units(73.4) == round(73.4 * rules.basal.units_per_kg)
    assert rules.source


def test_no_discharge_oral_entry_is_left_without_a_dose() -> None:
    """Every ``dose: ""`` entry carries a start dose or an authored dose text."""
    import glob
    import os

    import yaml

    from clinosim.modules.disease import protocol as p

    root = os.path.join(os.path.dirname(p.__file__), "reference_data")
    offenders = []
    for path in glob.glob(os.path.join(root, "*.yaml")):
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        block = (data.get("drugs") or {}).get("discharge_oral")
        if not isinstance(block, dict):
            continue
        for country in ("japan", "us"):
            for e in block.get(country) or []:
                if isinstance(e, dict) and e.get("dose") == "" and not (e.get("start_dose") or e.get("dose_text")):
                    offenders.append((os.path.basename(path), country, e.get("drug_id")))
    assert not offenders


def _bad(entry: dict) -> None:
    from clinosim.modules.disease.protocol import _validate_discharge_dose_schema

    with pytest.raises(ValueError):
        _validate_discharge_dose_schema("x", {"discharge_oral": {"us": [entry]}})


def test_schema_rejects_unknown_or_inconsistent_keys() -> None:
    from clinosim.modules.disease.protocol import _validate_discharge_dose_schema

    _validate_discharge_dose_schema(
        "x",
        {
            "discharge_oral": {
                "us": [
                    {
                        "drug_id": "a",
                        "dose": "",
                        "home_dose": "resume",
                        "start_dose": {"dose": "1mg", "route": "PO", "frequency": "daily"},
                    },
                    {"drug_id": "b", "dose": "", "start_dose": {"rule": "basal_insulin"}},
                ]
            }
        },
    )
    _bad({"drug_id": "a", "home_dose": "resume"})  # resume needs a start dose
    _bad({"drug_id": "a", "home_dose": "yes", "start_dose": {"dose": "1mg"}})
    _bad({"drug_id": "a", "start_dose": {"dose": "1mg", "bogus": 1}})
    _bad({"drug_id": "a", "start_dose": {"rule": "nonexistent_rule"}})
    _bad({"drug_id": "a", "start_dose": {"rule": "basal_insulin", "dose": "1mg"}})
    _bad({"drug_id": "a", "start_dose": {"dose": "either or"}})
    _bad({"drug_id": "a", "start_dose": {"route": "PO"}})
