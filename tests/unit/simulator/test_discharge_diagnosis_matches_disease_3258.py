"""Issue #3258: the discharge diagnosis names the disease the patient was
simulated with, never another candidate of the differential (viral pneumonia
for a bacterial one, a kidney stone for pyelonephritis, pneumonia for a
trauma admission); `diagnosis_correct` follows the same disease match."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.codes import code_exists
from clinosim.locale.loaders.demographics import map_diagnosis_code
from clinosim.modules.diagnosis.engine import initialize_differential
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator.inpatient import _derive_final_diagnosis
from clinosim.types.diagnosis import DiagnosisCandidate, DifferentialDiagnosis

pytestmark = pytest.mark.unit


def _derive(disease_id: str, differential: DifferentialDiagnosis, country: str = "US"):
    protocol = load_disease_protocol(disease_id)
    patient = SimpleNamespace(sex="F", age=60, chronic_conditions=[], patient_id="P-1")
    return _derive_final_diagnosis(
        differential=differential,
        protocol=protocol,
        secondary_protocol=None,
        secondary_disease_id=None,
        patient=patient,  # type: ignore[arg-type]
        config=SimpleNamespace(country=country),  # type: ignore[arg-type]
        rng=np.random.default_rng(0),
        vitals=[],
        mars=[],
        lab_results=[],
    )


def _diff(*rows: tuple[str, str, float], working: str | None = None) -> DifferentialDiagnosis:
    cands = [DiagnosisCandidate(disease_code=d, icd_code=i, display_name="", probability=p) for d, i, p in rows]
    cands.sort(key=lambda c: -c.probability)
    return DifferentialDiagnosis(candidates=cands, working_diagnosis=working or cands[0].disease_code)


def test_bacterial_pneumonia_is_not_discharged_as_viral_pneumonia() -> None:
    diff = _diff(("viral_pneumonia", "J12.9", 0.6), ("bacterial_pneumonia", "J18.9", 0.3), ("other", "R05", 0.1))
    dx, _ = _derive("bacterial_pneumonia", diff)
    assert dx.discharge_diagnosis_code in {"J18.9", "J18.1", "J13"}
    assert dx.diagnosis_correct is True


def test_influenza_is_not_discharged_as_pneumococcal_pneumonia() -> None:
    diff = _diff(("bacterial_pneumonia", "J13", 0.7), ("influenza", "J10.1", 0.3))
    dx, _ = _derive("influenza", diff)
    assert dx.discharge_diagnosis_code.startswith(("J10", "J11"))


def test_pyelonephritis_is_not_discharged_as_kidney_stone() -> None:
    diff = _diff(("nephrolithiasis", "N20.0", 0.6), ("urinary_tract_infection", "N39.0", 0.4))
    dx, _ = _derive("urinary_tract_infection", diff)
    assert dx.discharge_diagnosis_code in {"N39.0", "N10"}


@pytest.mark.parametrize(
    "disease_id", ["crush_injury_hand", "fall_from_height", "industrial_burn_severe", "electrical_injury"]
)
def test_injury_protocol_discharges_with_its_injury_code(disease_id: str) -> None:
    protocol = load_disease_protocol(disease_id)
    differential = initialize_differential(disease_id, 45, protocol_diagnostic=protocol.diagnostic)
    dx, _ = _derive(disease_id, differential)
    assert dx.discharge_diagnosis_code == protocol.icd_codes["primary"]
    assert dx.discharge_diagnosis_code != "J12.9"


def test_diagnosis_correct_false_when_no_disease_candidate_is_reachable() -> None:
    # A differential whose only candidate is another disease and a disease
    # without own progression: the primary code is still the disease's own.
    diff = _diff(("viral_pneumonia", "J12.9", 1.0))
    dx, _ = _derive("crush_injury_hand", diff)
    assert dx.discharge_diagnosis_code == "S67.2"


@pytest.mark.parametrize(
    "code,expected",
    [
        ("S67.2", "S67.20XA"),
        ("T31.2", "T31.20"),
        ("T75.4", "T75.4XXA"),
        ("S72.0", "S72.009A"),
        ("I21.0", "I21.09"),
        ("K85.1", "K85.10"),
        ("I63.3", "I63.30"),
    ],
)
def test_us_discharge_code_is_billable(code: str, expected: str) -> None:
    mapped = map_diagnosis_code(code, "US")
    assert mapped == expected
    assert code_exists("icd-10-cm", mapped)


def test_every_disease_discharge_code_is_billable_in_the_us() -> None:
    """The discharge codes a disease can reach (its primary code and its diagnosis
    progression) map to a code the CMS FY2027 order file flags billable."""
    import glob
    import json
    import os

    from clinosim.modules.diagnosis.engine import DIAGNOSIS_PROGRESSION

    snapshot = json.load(open("clinosim/codes/authoritative/icd10cm_2027_cms.json"))
    billable = {c["code"] for c in snapshot["concept"] if c["billable"]}
    bad: dict[str, str] = {}
    for path in glob.glob("clinosim/modules/disease/reference_data/*.yaml"):
        disease_id = os.path.basename(path)[:-5]
        protocol = load_disease_protocol(disease_id)
        progression = (protocol.diagnostic or {}).get("diagnosis_progression") or DIAGNOSIS_PROGRESSION
        codes = {protocol.icd_codes["primary"], *(row[1] for row in progression.get(disease_id, []))}
        for code in codes:
            target = map_diagnosis_code(code, "US")
            if target not in billable:
                bad[f"{disease_id}:{code}"] = target
    assert not bad
