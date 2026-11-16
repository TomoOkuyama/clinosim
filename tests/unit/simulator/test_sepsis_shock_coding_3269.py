"""Issue #3269: septic shock (R65.21) is coded only when the stay shows shock
physiology (a vasopressor given, MAP < 65 mmHg and lactate > 2 mmol/L,
Sepsis-3), severe sepsis (R65.20) only with organ dysfunction; diagnostic
confidence no longer picks the severity code. JP output carries the MHLW
ICD-10 code R57.2 (septic shock) for R65.21."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.codes import display
from clinosim.locale.loader import map_diagnosis_code
from clinosim.modules.diagnosis.engine import get_current_diagnosis_code
from clinosim.simulator.sepsis_severity import sepsis_severity_code
from clinosim.types.diagnosis import DiagnosisCandidate, DifferentialDiagnosis
from clinosim.types.encounter import MedicationAdministration, OrderResult, VitalSignRecord

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 3, 1, 10, 0)


def _vitals(*bp: tuple[int, int]) -> list[VitalSignRecord]:
    return [
        VitalSignRecord(timestamp=_T0 + timedelta(hours=4 * i), systolic_bp=s, diastolic_bp=d)
        for i, (s, d) in enumerate(bp)
    ]


def _lab(name: str, value: float) -> OrderResult:
    return OrderResult(result_datetime=_T0, lab_name=name, value=value)


def _mar(drug: str, status: str = "given") -> MedicationAdministration:
    return MedicationAdministration(order_id="ORD-1", drug_name=drug, scheduled_datetime=_T0, status=status)


_NORMOTENSIVE = _vitals((124, 71), (130, 75))
_HYPOTENSIVE = _vitals((84, 52), (100, 60))  # MAP 62.7 on the first reading
_NE = [_mar("Norepinephrine 0.1 ug/kg/min IV drip")]


def _sepsis_differential(confidence: float) -> DifferentialDiagnosis:
    return DifferentialDiagnosis(
        candidates=[
            DiagnosisCandidate(disease_code="sepsis", icd_code="A41.9", display_name="", probability=confidence),
            DiagnosisCandidate(disease_code="other", icd_code="R65.10", display_name="", probability=1 - confidence),
        ],
        working_diagnosis="sepsis",
    )


@pytest.mark.parametrize("confidence", [0.5, 0.75, 0.95, 0.999])
def test_confidence_no_longer_picks_a_severity_code(confidence: float) -> None:
    code, _ = get_current_diagnosis_code(_sepsis_differential(confidence))
    assert code == "A41.9"


@pytest.mark.parametrize("code", ["A41.9", "R65.20", "R65.21"])
def test_normotensive_stay_without_vasopressor_is_not_septic_shock(code: str) -> None:
    assert sepsis_severity_code(code, vitals=_NORMOTENSIVE, mars=[], lab_results=[_lab("Lactate", 1.4)]) == "A41.9"


def test_shock_physiology_with_norepinephrine_is_septic_shock() -> None:
    labs = [_lab("Lactate", 1.6), _lab("Lactate", 4.2)]
    assert sepsis_severity_code("A41.9", vitals=_HYPOTENSIVE, mars=_NE, lab_results=labs) == "R65.21"


def test_vasopressor_without_hypotension_is_not_septic_shock() -> None:
    labs = [_lab("Lactate", 4.2)]
    # A vasopressor is cardiovascular organ dysfunction (SOFA >= 3).
    assert sepsis_severity_code("R65.21", vitals=_NORMOTENSIVE, mars=_NE, lab_results=labs) == "R65.20"


def test_hypotension_and_vasopressor_without_raised_lactate_is_not_septic_shock() -> None:
    labs = [_lab("Lactate", 1.8)]
    assert sepsis_severity_code("R65.21", vitals=_HYPOTENSIVE, mars=_NE, lab_results=labs) == "R65.20"


def test_held_vasopressor_dose_is_not_a_vasopressor_given() -> None:
    labs = [_lab("Lactate", 4.2)]
    held = [_mar("Norepinephrine 0.1 ug/kg/min IV drip", status="held")]
    assert sepsis_severity_code("A41.9", vitals=_HYPOTENSIVE, mars=held, lab_results=labs) == "A41.9"


@pytest.mark.parametrize(
    "lab",
    [("Creatinine", 2.4), ("T_Bil", 2.1), ("Plt", 85.0)],
)
def test_organ_dysfunction_is_severe_sepsis(lab: tuple[str, float]) -> None:
    labs = [_lab(*lab)]
    assert sepsis_severity_code("A41.9", vitals=_NORMOTENSIVE, mars=[], lab_results=labs) == "R65.20"


def test_mild_lab_changes_stay_sepsis() -> None:
    labs = [_lab("Creatinine", 1.5), _lab("T_Bil", 1.4), _lab("Plt", 140.0)]
    assert sepsis_severity_code("R65.20", vitals=_NORMOTENSIVE, mars=[], lab_results=labs) == "A41.9"


def test_other_codes_pass_through() -> None:
    assert sepsis_severity_code("J18.9", vitals=_HYPOTENSIVE, mars=_NE, lab_results=[_lab("Lactate", 5.0)]) == "J18.9"


def test_jp_septic_shock_is_mhlw_r57_2() -> None:
    assert map_diagnosis_code("R65.21", "JP") == "R57.2"
    assert display("icd-10", "R57.2", "ja") == "敗血症性ショック"
    assert display("icd-10", "R57.2", "en") == "Septic shock"
    # Severe sepsis without shock stays SIRS of infectious origin with organ failure.
    assert map_diagnosis_code("R65.20", "JP") == "R65.1"
    assert map_diagnosis_code("R65.21", "US") == "R65.21"
