"""Integration tests for _bb_nursing_observations FHIR builder (Task 5).

Verifies that NEWS2/GCS/Braden/Morse/ADL/I&O produce valid survey Observations,
that US output contains no Japanese characters, and that LOINC-coded observations
satisfy the display != code invariant.
"""

import json
import re

import pytest

pytestmark = pytest.mark.integration

_JAPANESE_RE = re.compile(r"[぀-ヿ一-鿿]")


def _record() -> dict:
    return {
        "patient_id": "p1",
        "vital_signs": [
            {
                "consciousness_level": "A",
                "news2_score": 13,
                "gcs_score": 15,
                "timestamp": "2026-01-01T08:00:00",
            }
        ],
        "nursing_risk_assessments": [
            {
                "date": "2026-01-01",
                "braden_total": 14,
                "morse_total": 55,
                "fall_risk_level": "high",
            }
        ],
        "adl_assessments": [{"date": "2026-01-01", "barthel_score": 40}],
        "intake_output_records": [
            {
                "date": "2026-01-01",
                "intake_iv_ml": 1500,
                "intake_oral_ml": 0,
                "intake_other_ml": 0,
                "output_urine_ml": 1200,
                "output_drain_ml": 0,
                "output_other_ml": 0,
            }
        ],
    }


def _make_ctx(record: dict, country: str, patient_id: str = "p1", primary_enc_id: str = "enc1"):
    """Construct a minimal BundleContext for testing."""
    from clinosim.modules.output.fhir_r4.lib.common import BundleContext

    return BundleContext(
        record=record,
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": patient_id},
        patient_id=patient_id,
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id=primary_enc_id,
        patient_sex="",
    )


def test_nursing_observations_us_no_japanese():
    """US output must have no Japanese characters."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    assert obs, "no nursing observations built"
    assert not _JAPANESE_RE.search(json.dumps(obs)), "Japanese characters found in US output"


def test_resource_types_are_observation():
    """Every resource must have resourceType == Observation."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    assert all(o["resourceType"] == "Observation" for o in obs)


def test_category_is_survey():
    """Every Observation must have category containing the 'survey' code."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    for o in obs:
        codes = [c["code"] for cat in o.get("category", []) for c in cat.get("coding", [])]
        assert "survey" in codes, f"Observation {o['id']} missing survey category"


def test_ids_unique():
    """All observation ids within the output must be unique."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    ids = [o["id"] for o in obs]
    assert len(ids) == len(set(ids)), f"Duplicate observation ids: {ids}"


def test_subject_references_patient():
    """subject.reference must point to the Patient resource."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US", patient_id="p1")
    obs = _bb_nursing_observations(ctx)

    for o in obs:
        ref = o.get("subject", {}).get("reference", "")
        assert ref.startswith("Patient/"), f"Observation {o['id']} has bad subject ref: {ref}"


def test_encounter_reference_present():
    """When primary_enc_id is set, encounter reference must be on each Observation."""
    from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US", primary_enc_id="enc1")
    obs = _bb_nursing_observations(ctx)

    expected = f"Encounter/{resolve_encounter_id('enc1')}"
    for o in obs:
        enc_ref = o.get("encounter", {}).get("reference", "")
        assert enc_ref == expected, f"Observation {o['id']} missing or wrong encounter ref: {enc_ref!r}"


def test_news2_has_clinosim_custom_coding():
    """Session 58 Issue #269: NEWS2 does NOT have a canonical LOINC 2.82
    code (the previously-used `90557-9` is not in LOINC — the closest
    entry `90557-0` is unrelated). Emit under the clinosim-owned
    `nursing-scores` CodeSystem instead so validators either resolve or
    accept it as a locally-defined coding. Session 42 cycle 2 (C2-30)
    verification comment was mistaken."""
    from clinosim.codes import get_system_uri
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    news2_obs = [o for o in obs if o["id"].startswith("news2-")]
    assert news2_obs, "No NEWS2 observation found"
    expected_uri = get_system_uri("clinosim-nursing-scores")
    for o in news2_obs:
        codings = o["code"].get("coding", [])
        assert codings, "NEWS2 must have code.coding under the clinosim nursing-scores CS"
        assert codings[0]["system"] == expected_uri
        assert codings[0]["code"] == "NEWS2"
        # No leftover LOINC fallback under `http://loinc.org` with the retired 90557-9.
        assert not any(c.get("system") == get_system_uri("loinc") and c.get("code") == "90557-9" for c in codings)


def test_gcs_has_loinc_coding():
    """GCS Observation must have LOINC 9269-2 in code.coding."""
    from clinosim.codes import get_system_uri
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    gcs_obs = [o for o in obs if o["id"].startswith("gcs-")]
    assert gcs_obs, "No GCS observation found"
    loinc_uri = get_system_uri("loinc")
    for o in gcs_obs:
        codings = o["code"].get("coding", [])
        loinc_codes = [c["code"] for c in codings if c.get("system") == loinc_uri]
        assert "9269-2" in loinc_codes, f"GCS missing LOINC 9269-2, got: {codings}"


def test_loinc_display_not_equal_to_code():
    """For LOINC-coded observations, display must differ from the code value."""
    from clinosim.codes import get_system_uri
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    loinc_uri = get_system_uri("loinc")
    for country in ("US", "JP"):
        ctx = _make_ctx(_record(), country=country)
        obs = _bb_nursing_observations(ctx)
        for o in obs:
            for coding in o["code"].get("coding", []):
                if coding.get("system") == loinc_uri:
                    disp = coding.get("display", "")
                    code_val = coding.get("code", "")
                    assert disp != code_val, f"display == code ({code_val!r}) in {o['id']} for country={country}"


def test_braden_and_morse_present():
    """Braden and Morse observations must be generated from nursing_risk_assessments."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    braden_obs = [o for o in obs if o["id"].startswith("braden-")]
    morse_obs = [o for o in obs if o["id"].startswith("morse-")]
    assert braden_obs, "No Braden observation found"
    assert morse_obs, "No Morse observation found"


def test_morse_has_interpretation():
    """Morse observation must include interpretation when fall_risk_level is set."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    morse_obs = [o for o in obs if o["id"].startswith("morse-")]
    assert morse_obs, "No Morse observation found"
    for o in morse_obs:
        assert "interpretation" in o, f"Morse observation {o['id']} missing interpretation"


def test_barthel_present():
    """Barthel index Observation must be generated from adl_assessments."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    barthel_obs = [o for o in obs if o["id"].startswith("barthel-")]
    assert barthel_obs, "No Barthel observation found"


def test_intake_output_observations():
    """Fluid intake, urine output, and total output Observations must be generated."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    intake_obs = [o for o in obs if o["id"].startswith("intake-")]
    urine_obs = [o for o in obs if o["id"].startswith("urine-")]
    output_obs = [o for o in obs if o["id"].startswith("output-")]
    assert intake_obs, "No intake observation found"
    assert urine_obs, "No urine observation found"
    assert output_obs, "No total output observation found"


def test_intake_value_is_sum_of_components():
    """Fluid intake total must equal iv + oral + other."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    intake_obs = [o for o in obs if o["id"].startswith("intake-")]
    assert intake_obs
    # Record has iv=1500, oral=0, other=0 → total=1500
    assert intake_obs[0]["valueQuantity"]["value"] == 1500


def test_output_value_is_sum_of_components():
    """Fluid output total must equal urine + drain + other."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    output_obs = [o for o in obs if o["id"].startswith("output-")]
    assert output_obs
    # Record has urine=1200, drain=0, other=0 → total=1200
    assert output_obs[0]["valueQuantity"]["value"] == 1200


def test_fluid_observations_have_ml_unit():
    """Fluid volume Observations must use mL as unit."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="US")
    obs = _bb_nursing_observations(ctx)

    fluid_ids = ("intake-", "urine-", "output-")
    fluid_obs = [o for o in obs if any(o["id"].startswith(p) for p in fluid_ids)]
    assert fluid_obs
    for o in fluid_obs:
        unit = o.get("valueQuantity", {}).get("unit")
        assert unit == "mL", f"Expected mL unit, got {unit!r} in {o['id']}"


def test_jp_output_may_have_japanese():
    """JP output should have Japanese display text from lookup."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record(), country="JP")
    obs = _bb_nursing_observations(ctx)

    dumped = json.dumps(obs, ensure_ascii=False)
    # At least one Japanese character should appear in JP output (from code.text lookups)
    assert _JAPANESE_RE.search(dumped), "Expected Japanese text in JP output"


# ----- Assessment effectiveDateTime vs encounter admission_datetime (Issue #1437) -----
#
# Barthel / Braden / Morse / intake-output / urine output Observations
# were emitted with ``effectiveDateTime = <date>T00:00:00`` because the
# CIF ADL / nursing-risk / intake-output generators store ``date`` as
# a ``date`` object (day precision). When the actual admission lands
# late in the day (e.g. 18:03, 22:31), the assessment Observation
# precedes the Encounter.period.start it references — a temporal
# invariant violation. Verify on p=10000 s=360: 3,288 US / 3,894 JP
# such records across the six categories. Fix: when the assessment's
# date matches the admission date, emit the Observation at the
# encounter's admission time; on later days, use a nurse-shift-plausible
# hour (09:00) preserving the encounter's timezone.


def _record_with_encounter(admission_iso: str) -> dict:
    """Same shape as ``_record()`` but wired to a real inpatient
    encounter whose ``admission_datetime`` is late in the day."""
    from datetime import datetime as _dt

    admit = _dt.fromisoformat(admission_iso)
    return {
        "patient_id": "p1",
        "encounters": [
            {
                "encounter_id": "enc1",
                "encounter_type": "inpatient",
                "admission_datetime": admission_iso,
                "primary_nurse_id": "",
            }
        ],
        "nursing_risk_assessments": [
            {
                "date": admit.date(),
                "braden_total": 14,
                "morse_total": 55,
                "fall_risk_level": "high",
            }
        ],
        "adl_assessments": [{"date": admit.date(), "barthel_score": 40}],
        "intake_output_records": [
            {
                "date": admit.date(),
                "intake_iv_ml": 1500,
                "intake_oral_ml": 0,
                "intake_other_ml": 0,
                "output_urine_ml": 1200,
                "output_drain_ml": 0,
                "output_other_ml": 0,
            }
        ],
    }


def test_assessment_effective_ge_admission_when_same_day():
    """Every assessment Observation whose date equals the admission day
    must emit ``effectiveDateTime`` at or after ``admission_datetime`` —
    never at midnight of that day."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record_with_encounter("2025-10-20T18:03:00"), country="US")
    obs = _bb_nursing_observations(ctx)
    assert obs, "expected at least one nursing observation"
    admit_iso = "2025-10-20T18:03:00"
    for o in obs:
        eff = o.get("effectiveDateTime")
        if not eff:
            continue
        # accept optional TZ suffix — parse the local wall-clock portion
        eff_local = eff[:19]
        assert eff_local >= admit_iso[:19], (
            f"Observation {o['id']} effectiveDateTime {eff_local!r} precedes admission_datetime {admit_iso[:19]!r}"
        )


def test_assessment_effective_not_midnight_when_admission_late():
    """Guard against a regression where the emit path reverts to
    day-midnight — every assessment Observation must have a nonzero
    time-of-day when the encounter's admission is late."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record_with_encounter("2025-10-20T18:03:00"), country="US")
    obs = _bb_nursing_observations(ctx)
    assert obs
    for o in obs:
        eff = o.get("effectiveDateTime")
        if not eff:
            continue
        # e.g. "2025-10-20T00:00:00..." would fail
        assert "T00:00:00" not in eff[:19], (
            f"Observation {o['id']} effectiveDateTime {eff!r} still landed at day-midnight"
        )


def test_assessment_effective_uses_admission_time_when_same_day():
    """Day-0 assessments should emit at the encounter's admission time
    itself (nurse assessment on arrival)."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx(_record_with_encounter("2025-10-20T18:03:00"), country="US")
    obs = _bb_nursing_observations(ctx)
    admit_iso_prefix = "2025-10-20T18:03:00"
    for o in obs:
        eff = o.get("effectiveDateTime")
        if not eff:
            continue
        assert eff.startswith(admit_iso_prefix), (
            f"Observation {o['id']} expected day-0 effectiveDateTime to start with {admit_iso_prefix!r}, got {eff!r}"
        )


def test_empty_record_returns_empty_list():
    """No nursing data → empty observation list."""
    from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

    ctx = _make_ctx({}, country="US")
    obs = _bb_nursing_observations(ctx)
    assert obs == []
