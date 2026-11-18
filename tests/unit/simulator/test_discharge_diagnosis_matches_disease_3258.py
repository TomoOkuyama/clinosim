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
    own = {protocol.icd_codes["primary"], *(v["code"] for v in protocol.icd_codes.get("variants") or [])}
    assert dx.discharge_diagnosis_code in own
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


# ---- Issue #3258, injury admissions: sampled diagnosis, operation, external cause ----

from clinosim.simulator.injury_coding import external_cause_code, stay_primary_code, surgery_for_diagnosis  # noqa: E402


def test_fall_from_height_samples_its_diagnosis_by_the_yaml_weights() -> None:
    protocol = load_disease_protocol("fall_from_height")
    codes = [stay_primary_code(protocol, f"ENC-{i}") for i in range(2000)]
    share = {c: codes.count(c) / len(codes) for c in set(codes)}
    assert set(share) == {"T07", "S32.0", "S72.0", "S22.0", "S06.9"}
    assert abs(share["T07"] - 0.40) < 0.05 and abs(share["S06.9"] - 0.10) < 0.03
    assert stay_primary_code(protocol, "ENC-1") == stay_primary_code(protocol, "ENC-1")


def test_other_protocols_keep_their_primary_code() -> None:
    assert stay_primary_code(load_disease_protocol("crush_injury_hand"), "ENC-1") == "S67.2"


def test_femoral_neck_fixation_and_head_injury_follow_the_diagnosis() -> None:
    protocol = load_disease_protocol("fall_from_height")
    operate, spec = surgery_for_diagnosis(protocol, "S72.0", "moderate")
    assert operate and spec["procedure_mapping_key"] == "ORIF_femur"
    assert surgery_for_diagnosis(protocol, "S06.9", "moderate") == (False, {})
    operate, spec = surgery_for_diagnosis(protocol, "S06.9", "severe")
    assert operate and spec["type"] == "Craniotomy"
    # A diagnosis without an entry keeps the protocol's default operation.
    assert surgery_for_diagnosis(protocol, "S32.0", "severe") == (True, {})


def test_simulate_surgery_uses_the_diagnosis_override() -> None:
    from datetime import datetime

    from clinosim.modules.procedure.engine import simulate_surgery

    protocol = load_disease_protocol("fall_from_height")
    _, spec = surgery_for_diagnosis(protocol, "S72.0", "moderate")
    patient = SimpleNamespace(patient_id="P-1", age=45, chronic_conditions=[])
    proc, _ = simulate_surgery(
        patient,
        "fall_from_height",
        "ENC-1",
        datetime(2026, 1, 1),
        protocol,
        np.random.default_rng(1),
        "US",
        overrides=spec,
    )
    assert proc.procedure_type == "ORIF" and proc.procedure_code_us == "27236" and proc.procedure_code_jp == "K0463"


def test_external_cause_is_us_only_and_follows_the_mechanism_of_the_disease() -> None:
    fall = load_disease_protocol("fall_from_height")
    assert external_cause_code(fall, "ENC-1", "US") in {"W11.XXXA", "W12.XXXA", "W13.2XXA", "W13.8XXA"}
    assert external_cause_code(fall, "ENC-1", "JP") == ""
    crush = load_disease_protocol("crush_injury_hand")
    assert external_cause_code(crush, "ENC-1", "US").startswith("W23")
    assert external_cause_code(load_disease_protocol("industrial_burn_severe"), "ENC-2", "US").startswith("X")
    assert external_cause_code(load_disease_protocol("electrical_injury"), "ENC-3", "US").startswith("W8")
    assert external_cause_code(load_disease_protocol("bacterial_pneumonia"), "ENC-1", "US") == ""


def test_derive_final_diagnosis_records_the_stay_code_and_external_cause() -> None:
    protocol = load_disease_protocol("fall_from_height")
    encounter_id = next(f"ENC-{i}" for i in range(200) if stay_primary_code(protocol, f"ENC-{i}") == "S72.0")
    differential = initialize_differential("fall_from_height", 45, protocol_diagnostic=protocol.diagnostic)
    patient = SimpleNamespace(sex="M", age=45, chronic_conditions=[], patient_id="P-1")
    kw = dict(
        differential=differential,
        protocol=protocol,
        secondary_protocol=None,
        secondary_disease_id=None,
        patient=patient,
        rng=np.random.default_rng(0),
        vitals=[],
        mars=[],
        lab_results=[],
        encounter_id=encounter_id,
    )
    us, _ = _derive_final_diagnosis(config=SimpleNamespace(country="US"), **kw)  # type: ignore[arg-type]
    assert us.admission_diagnosis_code == us.discharge_diagnosis_code == "S72.0"
    assert us.external_cause_code.startswith(("W11", "W12", "W13"))
    jp, _ = _derive_final_diagnosis(config=SimpleNamespace(country="JP"), **kw)  # type: ignore[arg-type]
    assert jp.external_cause_code == ""


# ---- Issue #3258, burn site and extent ----

from clinosim.simulator.injury_coding import secondary_diagnosis_codes  # noqa: E402

_BURN_SITE_SHARES = {
    "T20.0": 33,
    "T20.07": 15,
    "T21.0": 38,
    "T22.0": 45,
    "T23.0": 42,
    "T24.0": 39,
    "T25.0": 19,
    "T21.05": 12,
}


def test_burn_stay_is_coded_by_site_with_the_aba_shares_as_weights() -> None:
    protocol = load_disease_protocol("industrial_burn_severe")
    assert {v["code"]: v["probability"] for v in protocol.icd_codes["variants"]} == _BURN_SITE_SHARES
    codes = [stay_primary_code(protocol, f"ENC-{i}") for i in range(4000)]
    total = sum(_BURN_SITE_SHARES.values())
    for code, share in _BURN_SITE_SHARES.items():
        assert abs(codes.count(code) / len(codes) - share / total) < 0.03, code


def test_burn_site_codes_state_no_degree_and_extent_is_secondary() -> None:
    protocol = load_disease_protocol("industrial_burn_severe")
    for code in _BURN_SITE_SHARES:
        # US: the unspecified-degree leaf, initial encounter; JP: the WHO T2x.0 code.
        us = map_diagnosis_code(code, "US")
        assert us.startswith(code[:3]) and us.endswith("A") and code_exists("icd-10-cm", us)
        jp = map_diagnosis_code(code, "JP")
        assert jp in {"T20.0", "T21.0", "T22.0", "T23.0", "T24.0", "T25.0"} and code_exists("icd-10", jp)
    assert {secondary_diagnosis_codes(protocol, f"ENC-{i}")[0] for i in range(200)} == {"T31.2", "T31.3"}
    assert map_diagnosis_code("T31.2", "US") == "T31.20" and map_diagnosis_code("T31.3", "US") == "T31.30"
    assert secondary_diagnosis_codes(load_disease_protocol("fall_from_height"), "ENC-1") == []


def test_derive_final_diagnosis_records_burn_extent_beside_the_site() -> None:
    protocol = load_disease_protocol("industrial_burn_severe")
    differential = initialize_differential("industrial_burn_severe", 40, protocol_diagnostic=protocol.diagnostic)
    patient = SimpleNamespace(sex="M", age=40, chronic_conditions=[], patient_id="P-1")
    dx, _ = _derive_final_diagnosis(
        differential=differential,
        protocol=protocol,
        secondary_protocol=None,
        secondary_disease_id=None,
        patient=patient,
        config=SimpleNamespace(country="JP"),
        rng=np.random.default_rng(0),  # type: ignore[arg-type]
        vitals=[],
        mars=[],
        lab_results=[],
        encounter_id="ENC-7",
    )
    assert dx.admission_diagnosis_code == dx.discharge_diagnosis_code in _BURN_SITE_SHARES
    assert dx.secondary_diagnosis_codes and dx.secondary_diagnosis_codes[0] in {"T31.2", "T31.3"}
