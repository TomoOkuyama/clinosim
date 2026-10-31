"""Bipolar disorder (F31) as a chronic condition with mood-stabilizer treatment (Issue #2142)."""

from __future__ import annotations

import pytest

from clinosim.codes import lookup
from clinosim.locale.loader import load_chronic_followup, load_code_mapping, load_demographics
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept
from clinosim.modules.patient.activator import _derive_home_medications
from clinosim.modules.population.condition_mutex import apply_depression_mutex
from clinosim.simulator.outpatient_dept import resolve_outpatient_department
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit

_MOOD_STABILIZERS = {
    "lithium carbonate": ("42351", "1179017"),
    "valproic acid": ("11118", "1139004"),
    "lamotrigine": ("28439", "1139009"),
}


@pytest.mark.parametrize("country", ["US", "JP"])
def test_prevalence_and_diagnosis_code(country: str) -> None:
    prev = load_demographics(country)["chronic_prevalence"]["F31"]
    bands = [float(v) for k, v in prev.items() if "-" in str(k)]
    assert 0.001 <= max(bands) <= 0.02 and prev["rng_isolated"] is True
    assert load_code_mapping("diagnosis", country)["F31"] == "F31.9"
    assert lookup("icd-10-cm" if country == "US" else "icd-10", "F31.9", "en")


def test_bipolar_subsumes_unipolar_depression() -> None:
    conditions = ["I10", "F32", "F31", "F33"]
    apply_depression_mutex(conditions)
    assert conditions == ["I10", "F31"]


def test_follow_up_with_psychiatry() -> None:
    assert "F31" in load_chronic_followup()
    assert resolve_outpatient_department("chronic_followup", "F31", None, None) == "psychiatry"


@pytest.mark.parametrize(("drug", "codes"), sorted(_MOOD_STABILIZERS.items()))
@pytest.mark.parametrize("country", ["US", "JP"])
def test_mood_stabilizer_codes(drug: str, codes: tuple[str, str], country: str) -> None:
    concept, _ = _resolve_medication_concept(drug, order_code="", country=country, route="PO")
    code = concept["coding"][0]["code"]
    if country == "US":
        assert code == codes[0]
    else:  # a full YJ product of the ingredient (Issue #2347)
        assert code.startswith(codes[1]) and len(code) == 12


def test_treatment_mix() -> None:
    stabilizer = antipsychotic = 0
    for i in range(400):
        names = {
            m.drug_name.lower()
            for m in _derive_home_medications(
                [ChronicCondition(code="F31", severity_score=0.5)], patient_id=f"P{i}", country="US", patient_age=35
            )
        }
        n_stab = len(names & set(_MOOD_STABILIZERS))
        assert n_stab <= 1  # one mood stabilizer (exclusive class)
        stabilizer += n_stab
        antipsychotic += bool(names & {"quetiapine", "aripiprazole", "olanzapine"})
    assert 0.55 <= stabilizer / 400 <= 0.8
    assert 0.2 <= antipsychotic / 400 <= 0.45


def test_lithium_users_get_lithium_levels() -> None:
    from clinosim.modules.monitoring.mapping import load_medication_monitoring

    labs = {m["lab"] for m in load_medication_monitoring()["Lithium carbonate"]["monitoring"]}
    assert {"Lithium", "TSH", "Creatinine"} <= labs
    assert load_code_mapping("lab", "JP")["Lithium"] == "3L320"


def test_adding_f31_leaves_other_residents_unchanged() -> None:
    """Residents without F31 keep an identical history with or without F31
    (isolated prevalence and onset draws); F31 holders only lose F32 / F33."""
    import numpy as np

    from clinosim.modules.longitudinal import engine as long_engine
    from clinosim.modules.population import aging
    from clinosim.modules.population import engine as pop

    def histories(drop_f31: bool) -> dict[str, list[str]]:
        demo = load_demographics("US")
        specs = long_engine.load_attribute_specs()
        if drop_f31:
            demo = {**demo, "chronic_prevalence": {k: v for k, v in demo["chronic_prevalence"].items() if k != "F31"}}
            specs = {k: v for k, v in specs.items() if k != "f31_onset"}
        orig_demo, orig_specs = pop._load_demographics, long_engine.load_attribute_specs
        pop._load_demographics = lambda _c: demo
        long_engine.load_attribute_specs = lambda: specs
        try:
            registry = pop.generate_population(800, "US", np.random.default_rng(342))
            for year in (2025, 2026, 2027):
                aging.advance_population(registry, year, "US")
        finally:
            pop._load_demographics, long_engine.load_attribute_specs = orig_demo, orig_specs
        return {p.person_id: sorted(p.chronic_conditions) for p in registry.persons.values()}

    with_f31, without = histories(drop_f31=False), histories(drop_f31=True)
    holders = {pid for pid, codes in with_f31.items() if "F31" in codes}
    assert holders
    assert {k: v for k, v in with_f31.items() if k not in holders} == {
        k: v for k, v in without.items() if k not in holders
    }
