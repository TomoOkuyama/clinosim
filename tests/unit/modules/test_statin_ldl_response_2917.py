"""LDL lowering by statin intensity (Issue #2917)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clinosim.modules.physiology import statin_response as sr
from clinosim.modules.physiology.engine import derive_lab_values, medication_flags_from_context
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import HomeMedication, PatientProfile

pytestmark = pytest.mark.unit


def _med(drug: str, dose: str) -> HomeMedication:
    return HomeMedication(drug_name=drug, dose=dose, route="PO", frequency="daily")


def _patient(*meds: HomeMedication, patient_id: str = "pt-2917") -> PatientProfile:
    patient = PatientProfile(patient_id=patient_id, age=60, sex="M")
    patient.current_medications = [_med("Amlodipine", "5mg"), *meds]
    return patient


def _lipids(patient: PatientProfile) -> dict[str, float]:
    flags = medication_flags_from_context(patient)
    labs = derive_lab_values(PhysiologicalState(), sex="M", age=60, has_dyslipidemia=True, **flags)  # type: ignore[arg-type]
    return {k: labs[k] for k in ("TC", "LDL", "HDL", "TG")}


@pytest.mark.parametrize(
    ("drug", "dose", "intensity"),
    [
        ("Atorvastatin", "5mg", "low"),  # JP starting dose, below ACC/AHA Table 3
        ("Atorvastatin", "10mg", "moderate"),
        ("Atorvastatin", "20mg", "moderate"),
        ("Atorvastatin", "40mg", "high"),
        ("Atorvastatin", "80mg", "high"),
        ("Rosuvastatin", "2.5mg", "low"),
        ("Rosuvastatin", "5mg", "moderate"),
        ("Rosuvastatin", "20mg", "high"),
        ("Simvastatin", "10mg", "low"),
        ("Simvastatin", "40mg", "moderate"),
        ("Atorvastatin", "", "moderate"),  # unreadable dose -> default intensity
        ("Amlodipine", "5mg", None),
    ],
)
def test_intensity_follows_acc_aha_table_3(drug: str, dose: str, intensity: str | None) -> None:
    assert sr.statin_intensity(_med(drug, dose)) == intensity


def test_a_dose_written_into_the_name_is_read() -> None:
    assert sr.statin_intensity("Atorvastatin 40mg") == "high"


def test_no_statin_leaves_the_untreated_lipids() -> None:
    untreated = derive_lab_values(PhysiologicalState(), sex="M", age=60, has_dyslipidemia=True)
    assert medication_flags_from_context(_patient())["statin_ldl_reduction"] == 0.0
    assert _lipids(_patient()) == {k: untreated[k] for k in ("TC", "LDL", "HDL", "TG")}
    assert medication_flags_from_context(None)["statin_ldl_reduction"] == 0.0


@pytest.mark.parametrize(
    ("dose", "drug", "lo", "hi"),
    [
        ("5mg", "Atorvastatin", 0.20, 0.30),
        ("10mg", "Atorvastatin", 0.30, 0.49),
        ("40mg", "Atorvastatin", 0.50, 0.60),
        ("20mg", "Rosuvastatin", 0.50, 0.60),
    ],
)
def test_ldl_falls_by_the_intensity_range_and_tc_follows(dose: str, drug: str, lo: float, hi: float) -> None:
    untreated = _lipids(_patient())
    for pid in ("a", "b", "c", "d", "e"):
        treated = _lipids(_patient(_med(drug, dose), patient_id=pid))
        reduction = 1 - treated["LDL"] / untreated["LDL"]
        assert lo <= reduction <= hi
        # TC falls by the same mg/dL; HDL and TG are unchanged (Friedewald holds).
        assert treated["TC"] == pytest.approx(untreated["TC"] - (untreated["LDL"] - treated["LDL"]))
        assert (treated["HDL"], treated["TG"]) == (untreated["HDL"], untreated["TG"])
        assert treated["LDL"] == pytest.approx(treated["TC"] - treated["HDL"] - treated["TG"] / 5)


def test_a_patient_keeps_their_responsiveness_and_titration_lowers_ldl() -> None:
    by_intensity = [sr.statin_ldl_reduction("pt-x", [_med("Atorvastatin", dose)]) for dose in ("5mg", "10mg", "40mg")]
    assert by_intensity == sorted(by_intensity)
    q = [(r - lo) / (hi - lo) for r, (lo, hi) in zip(by_intensity, sr.statin_ldl_response().ldl_reduction.values())]
    assert q == pytest.approx([q[0]] * 3)
    # Responders vary between patients, deterministically.
    spread = {round(sr.statin_ldl_reduction(f"pt-{i}", [_med("Atorvastatin", "10mg")]), 4) for i in range(20)}
    assert len(spread) == 20
    assert sr.statin_ldl_reduction("pt-x", [_med("Atorvastatin", "10mg")]) == by_intensity[1]


def test_the_most_intense_statin_counts() -> None:
    meds = [_med("Simvastatin", "10mg"), _med("Rosuvastatin", "20mg")]
    assert sr.statin_ldl_reduction("pt-y", meds) == sr.statin_ldl_reduction("pt-y", meds[1:])


def test_the_model_rejects_a_non_statin_and_overlapping_ranges() -> None:
    raw = sr.statin_ldl_response().model_dump()
    with pytest.raises(ValidationError):
        sr.StatinLdlResponse.model_validate({**raw, "intensity": {"amlodipine": {"moderate": 5}}})
    with pytest.raises(ValidationError):
        sr.StatinLdlResponse.model_validate({**raw, "ldl_reduction": {**raw["ldl_reduction"], "high": (0.40, 0.60)}})
    with pytest.raises(ValidationError):
        sr.StatinLdlResponse.model_validate({**raw, "intensity": {"atorvastatin": {"moderate": 40, "high": 10}}})
