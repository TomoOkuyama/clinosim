"""Issue #2301: monitoring, eval, audit and benchmarks resolve lab, drug and
diagnosis codes from the shared sources the generators use."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.types import Cohort
from clinosim.benchmarks.aki import _is_aki_encounter
from clinosim.benchmarks.harness import disease_icd_codes
from clinosim.benchmarks.sepsis import _is_sepsis_encounter
from clinosim.codes import get_system_uri
from clinosim.codes.drugs import resolve_drug
from clinosim.eval.axes import clinical
from clinosim.eval.engine import Outcome
from clinosim.locale.loader import lab_codes, load_code_mapping
from clinosim.modules.hai import hai_icd10_code, load_hai_codes
from clinosim.modules.monitoring.mapping import load_medication_monitoring, monitoring_lab_code
from clinosim.modules.output.fhir_r4.demographics.patient import resolve_patient_id

pytestmark = pytest.mark.unit


def test_monitoring_orders_use_the_lab_result_code() -> None:
    us_labs = load_code_mapping("lab", "US")
    for drug, entry in load_medication_monitoring().items():
        for m in entry["monitoring"]:
            assert "loinc" not in m, f"{drug}: the order code comes from the lab mapping"
            assert monitoring_lab_code(m["lab"]) == us_labs[m["lab"]]
    assert monitoring_lab_code("eGFR") == "48642-3"


def test_lab_codes_cover_both_locales() -> None:
    assert lab_codes("WBC") == (load_code_mapping("lab", "US")["WBC"], load_code_mapping("lab", "JP")["WBC"])
    assert lab_codes("not-a-lab") == ()


def test_audit_hai_codes_come_from_hai_codes_yaml() -> None:
    from clinosim.audit.registry import discover, get_registered

    discover()
    cfg = load_hai_codes()["hai_codes"]
    for module in ("hai", "antibiotic"):
        spec = get_registered()[module]
        for hai_type in ("cauti", "clabsi", "vap"):
            assert spec.clinical_acceptance[hai_type]["icd10_code"] == cfg[hai_type]["icd10_us_billable"]
            assert hai_icd10_code(hai_type) == cfg[hai_type]["icd10_us_billable"]


def test_eval_warfarin_codes_follow_catalog_and_mappings() -> None:
    name = resolve_drug("warfarin").names["en"]
    assert clinical._WARFARIN_RXNORM == resolve_drug("warfarin").codes["rxnorm"]
    assert clinical._WARFARIN_YJ_PREFIX == load_code_mapping("drug", "JP")[name][:7]
    assert clinical._PT_INR_LOINC == load_code_mapping("lab", "US")["PT_INR"]


def _write(dir_: Path, resource_type: str, rows: list[dict]) -> None:
    (dir_ / "fhir_r4").mkdir(parents=True, exist_ok=True)
    with (dir_ / "fhir_r4" / f"{resource_type}.ndjson").open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_eval_warfarin_check_works_on_a_jp_cohort(tmp_path: Path) -> None:
    pid = resolve_patient_id("p1")
    _write(tmp_path, "Patient", [{"resourceType": "Patient", "id": "p1"}])
    yj = load_code_mapping("drug", "JP")[resolve_drug("warfarin").names["en"]]
    _write(
        tmp_path,
        "MedicationRequest",
        [
            {
                "resourceType": "MedicationRequest",
                "id": "mr1",
                "subject": {"reference": f"Patient/{pid}"},
                "authoredOn": "2026-05-01",
                "medicationCodeableConcept": {"coding": [{"system": get_system_uri("yj"), "code": yj}]},
            }
        ],
    )
    _write(
        tmp_path,
        "Observation",
        [
            {
                "resourceType": "Observation",
                "id": "o1",
                "subject": {"reference": f"Patient/{pid}"},
                "effectiveDateTime": "2026-05-11T09:00:00Z",
                "code": {
                    "coding": [
                        {"system": "urn:oid:1.2.392.200119.4.1005", "code": load_code_mapping("lab", "JP")["PT_INR"]},
                        {"system": get_system_uri("loinc"), "code": load_code_mapping("lab", "US")["PT_INR"]},
                    ]
                },
                "valueQuantity": {"value": 1.0},
            }
        ],
    )
    checks = clinical.run(Cohort.open(tmp_path), "")
    warf = next(c for c in checks if c.name == "medication_lab_coherence_warfarin")
    assert warf.outcome is Outcome.FAIL
    assert warf.detail["violations"] == 1


def test_benchmark_labels_follow_the_disease_yaml() -> None:
    for code in disease_icd_codes("sepsis"):
        assert _is_sepsis_encounter({"clinical_diagnosis": {"admission_diagnosis_code": code}})
    # A40.0 is a sepsis variant the generator emits; the old A41/R65.2x literal missed it.
    assert _is_sepsis_encounter({"clinical_diagnosis": {"admission_diagnosis_code": "A40.0"}})
    assert not _is_sepsis_encounter({"clinical_diagnosis": {"admission_diagnosis_code": "J18.9"}})
    for code in disease_icd_codes("acute_kidney_injury"):
        assert _is_aki_encounter({"clinical_diagnosis": {"admission_diagnosis_code": code}})
    assert not _is_aki_encounter({"clinical_diagnosis": {"admission_diagnosis_code": "N18.4"}})
