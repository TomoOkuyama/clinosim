"""A sepsis stay is coded to the organism isolated from its blood culture
(Issue #3833); A41.9 only when no organism is identified. No draws."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.codes import lookup
from clinosim.modules.diagnosis.organism_code import isolate_refined_code, organism_sepsis_rules
from clinosim.modules.observation.microbiology import antibiotic_loinc_lookup
from clinosim.types.microbiology import MicrobiologyResult, SusceptibilityResult

pytestmark = pytest.mark.unit

T0 = datetime(2026, 3, 1, 9, 0)
PNEUMOCOCCUS, ECOLI, KLEBSIELLA, ENTEROCOCCUS, STAPH_AUREUS, PSEUDOMONAS = (
    "9861002",
    "112283007",
    "56415008",
    "78065002",
    "3092008",
    "52499004",
)


def _culture(organism: str = "", specimen: str = "blood", hours: float = 0, cefazolin: str = "") -> MicrobiologyResult:
    suscept = [SusceptibilityResult(antibiotic_loinc=antibiotic_loinc_lookup()["cefazolin"], interpretation=cefazolin)]
    return MicrobiologyResult(
        encounter_id="E1",
        specimen=specimen,
        collected_datetime=T0 + timedelta(hours=hours),
        growth=bool(organism),
        organism_snomed=organism,
        susceptibilities=suscept if cefazolin else [],
    )


@pytest.mark.parametrize(
    ("organism", "code"),
    [
        (PNEUMOCOCCUS, "A40.3"),
        (ECOLI, "A41.51"),
        (KLEBSIELLA, "A41.59"),
        (PSEUDOMONAS, "A41.52"),
        (ENTEROCOCCUS, "A41.81"),
    ],
)
def test_a_blood_isolate_refines_a419(organism: str, code: str) -> None:
    assert isolate_refined_code("sepsis", "A41.9", [_culture(organism)]) == code


def test_no_isolate_keeps_a419() -> None:
    assert isolate_refined_code("sepsis", "A41.9", []) == "A41.9"
    assert isolate_refined_code("sepsis", "A41.9", [_culture(), _culture(hours=24)]) == "A41.9"


def test_staph_aureus_follows_the_methicillin_marker() -> None:
    assert isolate_refined_code("sepsis", "A41.9", [_culture(STAPH_AUREUS, cefazolin="S")]) == "A41.01"
    assert isolate_refined_code("sepsis", "A41.9", [_culture(STAPH_AUREUS, cefazolin="R")]) == "A41.02"
    # no susceptibility result: no claim about methicillin
    assert isolate_refined_code("sepsis", "A41.9", [_culture(STAPH_AUREUS)]) == "A41.9"


def test_only_a_blood_isolate_counts_and_the_first_one_wins() -> None:
    assert isolate_refined_code("sepsis", "A41.9", [_culture(ECOLI, specimen="urine")]) == "A41.9"
    cultures = [_culture(KLEBSIELLA, hours=30), _culture(ECOLI, hours=2)]
    assert isolate_refined_code("sepsis", "A41.9", cultures) == "A41.51"


def test_other_codes_and_diseases_are_unchanged() -> None:
    assert isolate_refined_code("sepsis", "R65.21", [_culture(ECOLI)]) == "R65.21"
    assert isolate_refined_code("urinary_tract_infection", "A41.9", [_culture(ECOLI)]) == "A41.9"


def test_every_sepsis_code_is_in_the_code_tables() -> None:
    from clinosim.locale.loader import load_code_mapping

    rules = organism_sepsis_rules()
    codes = set(rules.organisms.values())
    for split in rules.susceptibility_splits.values():
        codes |= {split.susceptible, split.resistant}
    jp = load_code_mapping("diagnosis", "JP") or {}
    for code in codes:
        assert lookup("icd-10-cm", code, "en"), f"{code} missing in icd-10-cm"
        who = jp.get(code, code)
        assert lookup("icd-10", who, "ja"), f"{code} -> {who} missing a Japanese ICD-10 name"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_simulated_sepsis_stays_follow_their_blood_isolate(country: str) -> None:
    from clinosim.simulator import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    rules = organism_sepsis_rules()
    dataset = run_forced(
        ForcedScenario(disease_id="sepsis", count=40, severity="moderate"),
        SimulatorConfig(random_seed=11, country=country),
    )
    refined = 0
    for record in dataset.patients:
        code = record.clinical_diagnosis.discharge_diagnosis_code
        blood = [m for m in record.microbiology if m.growth and m.specimen == "blood"]
        if code.startswith(("A40", "A41")) and code != "A41.9":
            refined += 1
            assert blood, f"{code} without a blood isolate"
        elif code == "A41.9":
            assert not any(m.organism_snomed in rules.organisms for m in blood), f"A41.9 despite {blood}"
    assert refined >= 1
