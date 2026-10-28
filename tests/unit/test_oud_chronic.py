"""Opioid use disorder (F11) as a US chronic condition with MOUD (Issue #2146)."""

from __future__ import annotations

import pytest

from clinosim.codes import lookup
from clinosim.locale.loader import load_chronic_followup, load_demographics
from clinosim.modules.monitoring.mapping import load_medication_monitoring
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept
from clinosim.modules.patient.activator import _derive_home_medications
from clinosim.simulator.outpatient_dept import resolve_outpatient_department
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit

_MOUD = {"buprenorphine/naloxone": "352364", "methadone": "6813", "naltrexone": "7243"}


def test_us_prevalence_only() -> None:
    prev = load_demographics("US")["chronic_prevalence"]["F11.20"]
    bands = [float(v) for k, v in prev.items() if "-" in str(k)]
    assert 0.003 <= max(bands) <= 0.02 and prev["rng_isolated"] is True
    assert "F11.20" not in load_demographics("JP")["chronic_prevalence"]
    assert lookup("icd-10-cm", "F11.20", "en") == "Opioid dependence, uncomplicated"


def test_follow_up() -> None:
    assert "F11.20" in load_chronic_followup()
    assert resolve_outpatient_department("chronic_followup", "F11.20", None, None) == "psychiatry"


@pytest.mark.parametrize(("drug", "rxcui"), sorted(_MOUD.items()))
def test_moud_codes(drug: str, rxcui: str) -> None:
    concept, _ = _resolve_medication_concept(drug, order_code="", country="US")
    assert concept["coding"][0]["code"] == rxcui


def test_about_a_quarter_receive_moud() -> None:
    treated = 0
    for i in range(500):
        names = {
            m.drug_name.lower()
            for m in _derive_home_medications(
                [ChronicCondition(code="F11.20", severity_score=0.5)], patient_id=f"P{i}", country="US", patient_age=35
            )
        }
        hits = names & set(_MOUD)
        assert len(hits) <= 1  # one MOUD agent
        treated += bool(hits)
    assert 0.18 <= treated / 500 <= 0.40


def test_urine_drug_screen_for_agonist_therapy() -> None:
    mapping = load_medication_monitoring()
    for drug in ("Buprenorphine/Naloxone", "Methadone"):
        assert any(m["lab"] == "Urine_drug_screen" for m in mapping[drug]["monitoring"])


def test_adding_f11_leaves_other_conditions_unchanged() -> None:
    import numpy as np

    from clinosim.modules.population import aging
    from clinosim.modules.population import engine as pop

    def histories(drop: bool) -> dict[str, list[str]]:
        demo = load_demographics("US")
        if drop:
            demo = {
                **demo,
                "chronic_prevalence": {k: v for k, v in demo["chronic_prevalence"].items() if k != "F11.20"},
            }
        original = pop._load_demographics
        pop._load_demographics = lambda _c: demo
        try:
            registry = pop.generate_population(800, "US", np.random.default_rng(342))
            for year in (2025, 2026):
                aging.advance_population(registry, year, "US")
        finally:
            pop._load_demographics = original
        return {
            p.person_id: sorted(c for c in p.chronic_conditions if c != "F11.20") for p in registry.persons.values()
        }

    assert histories(drop=False) == histories(drop=True)


def test_monitoring_injects_the_qualitative_drug_screen() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from clinosim.modules.monitoring.enricher import enrich_medication_monitoring
    from clinosim.types.encounter import EncounterType
    from clinosim.types.patient import HomeMedication

    patient = SimpleNamespace(
        patient_id="POP-000901",
        sex="M",
        age=35,
        current_medications=[HomeMedication(drug_name="Buprenorphine/Naloxone 16mg/4mg", route="SL")],
        chronic_conditions=[],
    )
    enc = SimpleNamespace(
        encounter_id="ENC-901",
        encounter_type=EncounterType.OUTPATIENT,
        admission_datetime=datetime(2024, 5, 1, 9, 0),
        attending_physician_id="STAFF-DOC-001",
    )
    record = SimpleNamespace(patient=patient, encounters=[enc], orders=[], lab_results=[])
    enrich_medication_monitoring(SimpleNamespace(config=SimpleNamespace(country="US"), master_seed=1, records=[record]))
    results = [r for r in record.lab_results if r.lab_name == "Urine_drug_screen"]
    assert results and isinstance(results[0].value, str)
