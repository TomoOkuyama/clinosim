"""Issue #3448: a stay's discharge diagnosis keeps the admitted condition.

The confidence-keyed `diagnosis_progression` tables may only walk to the
stay's primary code, to a code that extends it (same code plus further
characters, e.g. S72.0 -> S72.00) or to a refinement the protocol declares in
`icd_codes.discharge_refinements` (organism, etiology, severity). A row that
is less specific than, or another condition from, the primary code (DKA ->
hyperglycemia, pyelonephritis -> UTI site not specified, asthma exacerbation
-> asthma unspecified) is never admissible."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.diagnosis.engine import DIAGNOSIS_PROGRESSION, discharge_code_is_admissible
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator.inpatient import _derive_final_diagnosis
from clinosim.types.diagnosis import DiagnosisCandidate, DifferentialDiagnosis

pytestmark = pytest.mark.unit

_PROTOCOL_DIR = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "disease" / "reference_data"
_DISEASES = sorted(p.stem for p in _PROTOCOL_DIR.glob("*.yaml"))


def _progression(disease_id: str) -> list[tuple[float, str]]:
    protocol = load_disease_protocol(disease_id)
    own = ((protocol.diagnostic or {}).get("diagnosis_progression") or {}).get(disease_id)
    return [(float(r[0]), str(r[1])) for r in (own or DIAGNOSIS_PROGRESSION.get(disease_id) or [])]


@pytest.mark.parametrize("disease_id", _DISEASES)
def test_every_progression_row_is_admissible(disease_id: str) -> None:
    protocol = load_disease_protocol(disease_id)
    icd = protocol.icd_codes or {}
    for _, code in _progression(disease_id):
        assert discharge_code_is_admissible(code, str(icd.get("primary") or ""), icd.get("discharge_refinements")), (
            f"{disease_id}: progression code {code} is neither the primary {icd.get('primary')}, an extension "
            "of it, nor declared in icd_codes.discharge_refinements"
        )


@pytest.mark.parametrize("disease_id", _DISEASES)
def test_declared_refinements_are_codes_of_the_protocol(disease_id: str) -> None:
    icd = load_disease_protocol(disease_id).icd_codes or {}
    declared = icd.get("discharge_refinements") or []
    assert isinstance(declared, list) and all(isinstance(c, str) and c for c in declared)
    assert len(declared) == len(set(declared))


def test_admissibility_rule() -> None:
    assert discharge_code_is_admissible("S72.00", "S72.0", None)
    assert discharge_code_is_admissible("N10", "N10", None)
    assert not discharge_code_is_admissible("N39.0", "N10", None)
    assert not discharge_code_is_admissible("E11.65", "E11.10", ["E11.11"])
    assert discharge_code_is_admissible("J13", "J18.9", ["J18.1", "J13"])


def test_dka_has_no_non_dka_variant() -> None:
    codes = {v["code"] for v in load_disease_protocol("diabetic_ketoacidosis").icd_codes["variants"]}
    assert codes and all(c[:5] in {"E10.1", "E11.1"} for c in codes), codes


def _derive(disease_id: str, confidence: float):
    protocol = load_disease_protocol(disease_id)
    primary = protocol.icd_codes["primary"]
    differential = DifferentialDiagnosis(
        candidates=[
            DiagnosisCandidate(disease_code=disease_id, icd_code=primary, display_name="", probability=confidence)
        ],
        working_diagnosis=disease_id,
    )
    patient = SimpleNamespace(sex="F", age=60, chronic_conditions=[], patient_id="P-1")
    dx, _ = _derive_final_diagnosis(
        differential=differential,
        protocol=protocol,
        secondary_protocol=None,
        secondary_disease_id=None,
        patient=patient,  # type: ignore[arg-type]
        config=SimpleNamespace(country="US"),  # type: ignore[arg-type]
        rng=np.random.default_rng(0),
        vitals=[],
        mars=[],
        lab_results=[],
    )
    return dx.discharge_diagnosis_code


@pytest.mark.parametrize("confidence", [0.3, 0.75, 0.95])
@pytest.mark.parametrize(
    "disease_id,expected",
    [
        ("diabetic_ketoacidosis", {"E11.10"}),
        ("urinary_tract_infection", {"N10"}),
        ("asthma_exacerbation", {"J45.21", "J45.41"}),
        ("acute_cholecystitis", {"K81.0", "K80.0"}),
        ("acute_appendicitis", {"K35.80", "K35.2"}),
        ("influenza", {"J10.1", "J10.0"}),
        ("deep_vein_thrombosis", {"I80.20"}),
        ("vertebral_compression_fracture", {"M80.08"}),
        ("ileus", {"K56.6"}),
    ],
)
def test_stay_never_loses_its_admitted_condition(disease_id: str, expected: set[str], confidence: float) -> None:
    assert _derive(disease_id, confidence) in expected


def test_septic_shock_is_a_secondary_code_after_the_infection() -> None:
    from clinosim.types.encounter import MedicationAdministration, OrderResult, VitalSignRecord

    t0 = datetime(2026, 3, 1, 10, 0)
    protocol = load_disease_protocol("sepsis")
    differential = DifferentialDiagnosis(
        candidates=[DiagnosisCandidate(disease_code="sepsis", icd_code="A41.9", display_name="", probability=0.95)],
        working_diagnosis="sepsis",
    )
    dx, _ = _derive_final_diagnosis(
        differential=differential,
        protocol=protocol,
        secondary_protocol=None,
        secondary_disease_id=None,
        patient=SimpleNamespace(sex="F", age=70, chronic_conditions=[], patient_id="P-1"),  # type: ignore[arg-type]
        config=SimpleNamespace(country="US"),  # type: ignore[arg-type]
        rng=np.random.default_rng(0),
        vitals=[VitalSignRecord(timestamp=t0, systolic_bp=84, diastolic_bp=52)],
        mars=[
            MedicationAdministration(
                order_id="O-1", drug_name="Norepinephrine 0.1 ug/kg/min IV drip", scheduled_datetime=t0, status="given"
            )
        ],
        lab_results=[OrderResult(result_datetime=t0 + timedelta(hours=1), lab_name="Lactate", value=4.2)],
    )
    assert dx.discharge_diagnosis_code == "A41.9"
    assert "R65.21" in dx.secondary_diagnosis_codes
