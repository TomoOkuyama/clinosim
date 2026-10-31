"""Schizophrenia (F20) as a chronic condition with antipsychotic treatment (Issue #2140)."""

from __future__ import annotations

import pytest

from clinosim.codes import lookup
from clinosim.locale.loader import load_chronic_followup, load_code_mapping, load_demographics
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept
from clinosim.modules.patient.activator import _derive_home_medications
from clinosim.simulator.outpatient_dept import resolve_outpatient_department
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit

_ANTIPSYCHOTICS = {
    "aripiprazole": ("89013", "1179045"),
    "risperidone": ("35636", "1179038"),
    "olanzapine": ("61381", "1179044"),
    "quetiapine": ("51272", "1179042"),
}


@pytest.mark.parametrize("country", ["US", "JP"])
def test_prevalence_and_diagnosis_code(country: str) -> None:
    prev = load_demographics(country)["chronic_prevalence"]["F20"]
    bands = [float(v) for k, v in prev.items() if "-" in str(k)]
    assert 0.003 <= max(bands) <= 0.012 and prev["rng_isolated"] is True
    assert load_code_mapping("diagnosis", country)["F20"] == "F20.9"
    system = "icd-10-cm" if country == "US" else "icd-10"
    assert lookup(system, "F20.9", "en")


def test_follow_up_with_psychiatry() -> None:
    assert "F20" in load_chronic_followup()
    assert resolve_outpatient_department("chronic_followup", "F20", None, None) == "psychiatry"


@pytest.mark.parametrize(("drug", "codes"), sorted(_ANTIPSYCHOTICS.items()))
@pytest.mark.parametrize("country", ["US", "JP"])
def test_antipsychotic_codes(drug: str, codes: tuple[str, str], country: str) -> None:
    concept, _ = _resolve_medication_concept(drug, order_code="", country=country, route="PO")
    code = concept["coding"][0]["code"]
    if country == "US":
        assert code == codes[0]
    else:  # a full YJ product of the ingredient (Issue #2347)
        assert code.startswith(codes[1]) and len(code) == 12


def test_most_patients_take_one_antipsychotic() -> None:
    counts = []
    for i in range(300):
        meds = _derive_home_medications(
            [ChronicCondition(code="F20", severity_score=0.5)], patient_id=f"P{i}", country="US", patient_age=35
        )
        counts.append(sum(m.drug_name.lower() in _ANTIPSYCHOTICS for m in meds))
    assert max(counts) == 1  # one antipsychotic (exclusive class)
    assert 0.7 <= sum(counts) / len(counts) <= 0.95


def test_adding_f20_leaves_other_conditions_unchanged() -> None:
    """Prevalence draw and yearly onset event both use sub-RNGs, so the
    rest of every resident's history is identical with or without F20."""
    import numpy as np

    from clinosim.modules.longitudinal import engine as long_engine
    from clinosim.modules.population import aging
    from clinosim.modules.population import engine as pop

    def histories(drop_f20: bool) -> dict[str, list[str]]:
        demo = load_demographics("US")
        specs = long_engine.load_attribute_specs()
        if drop_f20:
            demo = {**demo, "chronic_prevalence": {k: v for k, v in demo["chronic_prevalence"].items() if k != "F20"}}
            specs = {k: v for k, v in specs.items() if k != "f20_onset"}
        orig_demo, orig_specs = pop._load_demographics, long_engine.load_attribute_specs
        pop._load_demographics = lambda _c: demo
        long_engine.load_attribute_specs = lambda: specs
        try:
            registry = pop.generate_population(800, "US", np.random.default_rng(342))
            for year in (2025, 2026, 2027):
                aging.advance_population(registry, year, "US")
        finally:
            pop._load_demographics, long_engine.load_attribute_specs = orig_demo, orig_specs
        return {p.person_id: sorted(c for c in p.chronic_conditions if c != "F20") for p in registry.persons.values()}

    assert histories(drop_f20=False) == histories(drop_f20=True)
