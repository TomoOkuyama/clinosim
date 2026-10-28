"""Toxicology labs for psychiatric medical clearance; qualitative ED labs (Issue #2138)."""

from __future__ import annotations

from datetime import datetime

import pytest
import yaml

from clinosim import determinism
from clinosim.locale.loader import load_code_mapping, load_demographics
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.observation.engine import BASELINE_LAB_NORMALS, LAB_UNITS
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit

pytestmark = pytest.mark.unit

_TOX = {
    "Ethanol": ("5643-2", "3Z040", "mg/dL"),
    "Acetaminophen_level": ("3298-7", "3L005", "ug/mL"),
    "Salicylate": ("4024-6", "3M205", "mg/dL"),
    "Urine_drug_screen": ("69739-1", "3L970", "{qualitative}"),
}


@pytest.mark.parametrize("analyte", sorted(_TOX))
def test_tox_analytes_are_registered(analyte: str) -> None:
    loinc, jlac, unit = _TOX[analyte]
    assert load_code_mapping("lab", "US")[analyte] == loinc
    assert load_code_mapping("lab", "JP")[analyte] == jlac
    assert LAB_UNITS[analyte] == unit
    loinc_names = yaml.safe_load(open("clinosim/codes/data/loinc.yaml", encoding="utf-8"))
    assert loinc in (loinc_names.get("codes") or loinc_names)
    if unit != "{qualitative}":
        assert analyte in BASELINE_LAB_NORMALS


def _ed_labs(condition: str, severity: str = "moderate", seeds: int = 6) -> dict[str, list]:
    cond = load_encounter_condition(condition)
    out: dict[str, list] = {}
    for seed in range(seeds):
        rng = determinism.default_rng(seed)
        roster = generate_roster("medium", "US", rng)
        person = PersonRecord(
            person_id=f"T-{seed}", household_id="H", age=40, sex="F", date_of_birth=datetime(1984, 1, 1).date()
        )
        patient = activate_patient(person, rng, load_demographics("US"))
        record = _simulate_ed_visit(
            patient, {"name": condition, **cond}, datetime(2024, 6, 1, 14), roster, rng, force_severity=severity
        )
        for r in record.lab_results:
            out.setdefault(r.lab_name, []).append(r.value)
    return out


def test_psychiatric_clearance_orders_tox_labs() -> None:
    labs = _ed_labs("suicidal_ideation_depression")
    for analyte in ("Ethanol", "Urine_drug_screen", "Acetaminophen_level"):
        assert analyte in labs
    assert all(isinstance(v, str) for v in labs["Urine_drug_screen"])
    assert all(v < 10 for v in labs["Acetaminophen_level"])  # no co-ingestion


def test_qualitative_ed_labs_are_not_dropped() -> None:
    # Urinalysis is ordered with probability 0.9 for uncomplicated UTI.
    spec = [
        lab for lab in load_encounter_condition("uti_uncomplicated")["workup"]["labs"] if lab["test"] == "Urinalysis"
    ]
    assert spec
    labs = _ed_labs("uti_uncomplicated", seeds=4)
    assert "Urinalysis" in labs


def test_condition_specific_qualitative_results() -> None:
    from collections import Counter

    uti = Counter(_ed_labs("uti_uncomplicated", seeds=20).get("Urinalysis", []))
    assert uti and uti.get("Normal", 0) / sum(uti.values()) < 0.1  # pyuria in cystitis
    colic = Counter(_ed_labs("renal_colic", seeds=20).get("Urinalysis", []))
    assert colic and sum(n for v, n in colic.items() if "blood" in v) / sum(colic.values()) > 0.6  # hematuria


def test_legacy_jp_coding_never_emits_an_empty_code() -> None:
    from clinosim.modules.output.fhir_r4.labs.coding_strategy import LegacyJSLMStrategy

    codings = LegacyJSLMStrategy().emit_codings(lab_name="Urinalysis", order={}, result={}, country="JP")
    assert codings and all(c["code"] for c in codings)
    assert any(c["code"] == "24357-6" for c in codings)


def test_uncoded_jp_qualitative_lab_emits_text_only_code() -> None:
    from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation

    obs = _build_lab_observation(
        {"order_id": "O1", "display_name": "Rapid_Strep"},
        {"lab_name": "Rapid_Strep", "value": "Negative", "unit": "{qualitative}"},
        "P1",
        0,
        "JP",
        encounter_id="E1",
    )
    assert obs is not None
    assert obs["code"]["text"] == "A群溶連菌迅速抗原"
    assert all(c.get("code") for c in obs["code"].get("coding", []))
