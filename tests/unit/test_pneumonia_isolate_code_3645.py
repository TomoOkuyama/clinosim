"""An organism-specific pneumonia code follows an isolate (Issue #3645): J13
only for a pneumococcal isolate, never from the diagnostic confidence alone."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.codes import lookup
from clinosim.modules.diagnosis.engine import DIAGNOSIS_PROGRESSION, discharge_code_is_admissible
from clinosim.modules.diagnosis.organism_code import isolate_refined_code, organism_pneumonia_rules
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.types.microbiology import MicrobiologyResult

pytestmark = pytest.mark.unit

T0 = datetime(2026, 3, 1, 9, 0)
PNEUMOCOCCUS, KLEBSIELLA, STAPH_AUREUS = "9861002", "56415008", "3092008"


def _culture(specimen: str, organism: str = "", hours: float = 0) -> MicrobiologyResult:
    return MicrobiologyResult(
        encounter_id="E1",
        specimen=specimen,
        collected_datetime=T0 + timedelta(hours=hours),
        reported_datetime=T0 + timedelta(hours=hours + 48),
        growth=bool(organism),
        organism_snomed=organism,
    )


def test_confidence_alone_does_not_give_the_pneumococcal_code() -> None:
    for _confidence, code in DIAGNOSIS_PROGRESSION["bacterial_pneumonia"]:
        assert code != "J13"
    assert "J13" not in [
        c
        for _t, c in (load_disease_protocol("bacterial_pneumonia").diagnostic or {})
        .get("diagnosis_progression", {})
        .get("bacterial_pneumonia", [])
    ]


def test_negative_or_missing_cultures_keep_the_non_specific_code() -> None:
    negative = [_culture("blood"), _culture("blood", hours=24), _culture("sputum")]
    assert isolate_refined_code("bacterial_pneumonia", "J18.1", negative) == "J18.1"
    assert isolate_refined_code("bacterial_pneumonia", "J18.9", []) == "J18.9"


def test_a_pneumococcal_isolate_gives_j13() -> None:
    assert isolate_refined_code("bacterial_pneumonia", "J18.1", [_culture("sputum", PNEUMOCOCCUS)]) == "J13"
    assert isolate_refined_code("bacterial_pneumonia", "J18.9", [_culture("blood", PNEUMOCOCCUS)]) == "J13"


def test_another_organism_gives_its_own_code() -> None:
    assert isolate_refined_code("bacterial_pneumonia", "J18.1", [_culture("sputum", KLEBSIELLA)]) == "J15.0"


def test_an_organism_without_a_one_to_one_code_keeps_the_non_specific_code() -> None:
    assert isolate_refined_code("bacterial_pneumonia", "J18.1", [_culture("sputum", STAPH_AUREUS)]) == "J18.1"


def test_the_sputum_isolate_is_preferred_to_the_blood_isolate() -> None:
    cultures = [_culture("blood", KLEBSIELLA, 0), _culture("sputum", PNEUMOCOCCUS, 5)]
    assert isolate_refined_code("bacterial_pneumonia", "J18.1", cultures) == "J13"


def test_other_diseases_and_already_specific_codes_are_unchanged() -> None:
    assert isolate_refined_code("aspiration_pneumonia", "J69.0", [_culture("sputum", PNEUMOCOCCUS)]) == "J69.0"
    assert isolate_refined_code("bacterial_pneumonia", "J15.0", [_culture("sputum", PNEUMOCOCCUS)]) == "J15.0"


def test_every_isolate_code_is_declared_and_in_the_code_tables() -> None:
    rules = organism_pneumonia_rules()
    icd = load_disease_protocol("bacterial_pneumonia").icd_codes
    for snomed, code in rules.organisms.items():
        assert discharge_code_is_admissible(code, "J18.9", icd.get("discharge_refinements")), code
        assert lookup("icd-10-cm", code, "en"), f"{snomed}: {code} missing in icd-10-cm"
        assert lookup("icd-10", code, "ja"), f"{snomed}: {code} missing a Japanese ICD-10 name"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_simulated_stays_carry_an_organism_code_only_with_its_isolate(country: str) -> None:
    from clinosim.simulator import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    organism_codes = organism_pneumonia_rules().organisms
    dataset = run_forced(
        ForcedScenario(disease_id="bacterial_pneumonia", count=40, severity="moderate"),
        SimulatorConfig(random_seed=11, country=country),
    )
    coded = 0
    for record in dataset.patients:
        code = record.clinical_diagnosis.discharge_diagnosis_code
        isolates = {m.organism_snomed for m in record.microbiology if m.growth}
        if code in organism_codes.values():
            coded += 1
            assert any(organism_codes.get(o) == code for o in isolates), f"{code} without its isolate: {isolates}"
        elif isolates & set(organism_codes):
            assert code not in organism_pneumonia_rules().refines, f"{code} despite an isolate: {isolates}"
    assert coded >= 1
