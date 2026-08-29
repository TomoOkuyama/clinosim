"""Issue #854 Bucket A row 4 (PR-obs-standalone): 13 remaining stand-alone
Observation families migrate to opaque id + identifier round-trip.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878 [lab] → #879 [vs/gcs/news2]) to every remaining Observation family
in Bucket A row 4. Post-#854:

Nursing (from ``procedures/nursing.py``):
    braden-*    → braden-<12hex>    (19 chars)
    morse-*     → morse-<12hex>     (18 chars)
    barthel-*   → barthel-<12hex>   (20 chars)
    intake-*    → intake-<12hex>    (19 chars)
    urine-*     → urine-<12hex>     (18 chars)
    output-*    → output-<12hex>    (19 chars)

Demographics / SDOH (from ``demographics/``):
    blood-abo-* → blood-abo-<12hex> (22 chars)
    blood-rh-*  → blood-rh-<12hex>  (21 chars)
    smoking-*   → smoking-<12hex>   (20 chars)
    alcohol-*   → alcohol-<12hex>   (20 chars)
    occupation-* → occupation-<12hex> (23 chars)

Encounter / condition (from ``encounters/`` / ``conditions/``):
    carelevel-*  → carelevel-<12hex>  (22 chars)
    codestatus-* → codestatus-<12hex> (23 chars)

All families are stand-alone (no cross-reference cascade); the guard
mirrors PR #879 (vs/gcs/news2). Structural key = pre-#854 id body
without prefix — always ``{patient_id}`` (patient-scoped) or
``{enc or patient_id}-{i}`` (encounter-scoped).
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.conditions.code_status import (
    CODE_STATUS_KEY_SYSTEM,
    _bb_code_status,
    _resolve_code_status_id,
)
from clinosim.modules.output.fhir_r4.demographics.patient import (
    OCCUPATION_KEY_SYSTEM,
    _build_occupation_observation,
    _resolve_occupation_id,
)
from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import (
    ALCOHOL_USE_KEY_SYSTEM,
    SMOKING_STATUS_KEY_SYSTEM,
    _bb_alcohol_use,
    _bb_smoking_status,
    _resolve_alcohol_use_id,
    _resolve_smoking_status_id,
)
from clinosim.modules.output.fhir_r4.encounters.care_level import (
    CARE_LEVEL_KEY_SYSTEM,
    _bb_care_level,
    _resolve_care_level_id,
)
from clinosim.modules.output.fhir_r4.labs.blood_type import (
    BLOOD_ABO_KEY_SYSTEM,
    BLOOD_RH_KEY_SYSTEM,
    _bb_blood_type,
    _resolve_blood_abo_id,
    _resolve_blood_rh_id,
)
from clinosim.modules.output.fhir_r4.procedures.nursing import (
    BARTHEL_SCORE_KEY_SYSTEM,
    BRADEN_SCORE_KEY_SYSTEM,
    INTAKE_OBSERVATION_KEY_SYSTEM,
    MORSE_SCORE_KEY_SYSTEM,
    OUTPUT_OBSERVATION_KEY_SYSTEM,
    URINE_OUTPUT_OBSERVATION_KEY_SYSTEM,
    _bb_nursing_observations,
    _resolve_barthel_score_id,
    _resolve_braden_score_id,
    _resolve_intake_observation_id,
    _resolve_morse_score_id,
    _resolve_output_observation_id,
    _resolve_urine_output_observation_id,
)

pytestmark = pytest.mark.unit


def _opaque_pattern(prefix: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(prefix)}[0-9a-f]{{12}}$")


_PATTERNS = {
    "braden-": _opaque_pattern("braden-"),
    "morse-": _opaque_pattern("morse-"),
    "barthel-": _opaque_pattern("barthel-"),
    "intake-": _opaque_pattern("intake-"),
    "urine-": _opaque_pattern("urine-"),
    "output-": _opaque_pattern("output-"),
    "blood-abo-": _opaque_pattern("blood-abo-"),
    "blood-rh-": _opaque_pattern("blood-rh-"),
    "smoking-": _opaque_pattern("smoking-"),
    "alcohol-": _opaque_pattern("alcohol-"),
    "occupation-": _opaque_pattern("occupation-"),
    "carelevel-": _opaque_pattern("carelevel-"),
    "codestatus-": _opaque_pattern("codestatus-"),
}


# === Resolver contracts (13 families) ===

_RESOLVERS = [
    (_resolve_braden_score_id, "braden-", BRADEN_SCORE_KEY_SYSTEM, "braden-score-observation-key"),
    (_resolve_morse_score_id, "morse-", MORSE_SCORE_KEY_SYSTEM, "morse-score-observation-key"),
    (_resolve_barthel_score_id, "barthel-", BARTHEL_SCORE_KEY_SYSTEM, "barthel-score-observation-key"),
    (_resolve_intake_observation_id, "intake-", INTAKE_OBSERVATION_KEY_SYSTEM, "intake-observation-key"),
    (
        _resolve_urine_output_observation_id,
        "urine-",
        URINE_OUTPUT_OBSERVATION_KEY_SYSTEM,
        "urine-output-observation-key",
    ),
    (_resolve_output_observation_id, "output-", OUTPUT_OBSERVATION_KEY_SYSTEM, "fluid-output-observation-key"),
    (_resolve_blood_abo_id, "blood-abo-", BLOOD_ABO_KEY_SYSTEM, "blood-abo-observation-key"),
    (_resolve_blood_rh_id, "blood-rh-", BLOOD_RH_KEY_SYSTEM, "blood-rh-observation-key"),
    (_resolve_smoking_status_id, "smoking-", SMOKING_STATUS_KEY_SYSTEM, "smoking-status-observation-key"),
    (_resolve_alcohol_use_id, "alcohol-", ALCOHOL_USE_KEY_SYSTEM, "alcohol-use-observation-key"),
    (_resolve_occupation_id, "occupation-", OCCUPATION_KEY_SYSTEM, "occupation-observation-key"),
    (_resolve_care_level_id, "carelevel-", CARE_LEVEL_KEY_SYSTEM, "care-level-observation-key"),
    (_resolve_code_status_id, "codestatus-", CODE_STATUS_KEY_SYSTEM, "code-status-observation-key"),
]


@pytest.mark.parametrize("resolver,prefix,key_system,kind_slug", _RESOLVERS)
def test_resolver_opaque_shape(resolver, prefix, key_system, kind_slug) -> None:
    result = resolver("ENC-POP-000012-abc")
    assert _PATTERNS[prefix].match(result), f"got {result!r} for prefix {prefix!r}"
    assert len(result) == len(prefix) + 12


@pytest.mark.parametrize("resolver,prefix,key_system,kind_slug", _RESOLVERS)
def test_resolver_deterministic(resolver, prefix, key_system, kind_slug) -> None:
    key = "ENC-POP-000012-abc"
    assert resolver(key) == resolver(key)


@pytest.mark.parametrize("resolver,prefix,key_system,kind_slug", _RESOLVERS)
def test_key_system_uri_shape(resolver, prefix, key_system, kind_slug) -> None:
    assert key_system == f"urn:clinosim:identifier:{kind_slug}"


def test_all_13_families_produce_distinct_ids_from_same_key() -> None:
    """Distinct prefixes ensure the 13 families' opaque id spaces do not collide."""
    key = "POP-000123-42"
    ids = {resolver(key) for resolver, _, _, _ in _RESOLVERS}
    assert len(ids) == 13, f"expected 13 distinct ids, got {len(ids)}: {ids!r}"


# === Emit-path smoke tests (one per family) ===


def _nursing_ctx(**overrides) -> SimpleNamespace:
    base = {
        "record": {
            "patient": {"patient_id": "POP-000002"},
            "vital_signs": [],
            "encounters": [{"primary_nurse_id": "STAFF-N-001"}],
            "nursing_risk_assessments": [
                {"date": "2026-05-12", "braden_total": 18, "morse_total": 25, "fall_risk_level": "low"}
            ],
            "adl_assessments": [{"date": "2026-05-12", "barthel_score": 60}],
            "intake_output_records": [
                {
                    "date": "2026-05-12",
                    "intake_iv_ml": 1000,
                    "intake_oral_ml": 500,
                    "output_urine_ml": 1200,
                    "output_drain_ml": 50,
                    "output_other_ml": 20,
                }
            ],
        },
        "country": "JP",
        "roster_map": {},
        "hospital_config": {},
        "patient_data": {"patient_id": "POP-000002"},
        "patient_id": "POP-000002",
        "primary_enc_id": "ENC-001",
    }
    for k, v in overrides.items():
        base[k] = v
    return SimpleNamespace(**base)


def _find_by_prefix(resources: list[dict], prefix: str) -> dict | None:
    for r in resources:
        if r.get("id", "").startswith(prefix):
            return r
    return None


def _assert_family_shape(resource: dict, prefix: str, key_system: str, expected_structural_key: str) -> None:
    assert resource is not None, f"no Observation emitted for prefix {prefix!r}"
    assert _PATTERNS[prefix].match(resource["id"]), f"non-opaque id for {prefix!r}: {resource['id']!r}"
    idents = resource.get("identifier") or []
    key_idents = [i for i in idents if i.get("system") == key_system]
    assert len(key_idents) == 1, f"expected exactly 1 {key_system} identifier, got {idents!r}"
    assert key_idents[0]["value"] == expected_structural_key


def test_bb_nursing_emit_all_6_families_have_opaque_ids_with_identifier() -> None:
    ctx = _nursing_ctx()
    resources = _bb_nursing_observations(ctx)
    for prefix, key_system in [
        ("braden-", BRADEN_SCORE_KEY_SYSTEM),
        ("morse-", MORSE_SCORE_KEY_SYSTEM),
        ("barthel-", BARTHEL_SCORE_KEY_SYSTEM),
        ("intake-", INTAKE_OBSERVATION_KEY_SYSTEM),
        ("urine-", URINE_OUTPUT_OBSERVATION_KEY_SYSTEM),
        ("output-", OUTPUT_OBSERVATION_KEY_SYSTEM),
    ]:
        r = _find_by_prefix(resources, prefix)
        _assert_family_shape(r, prefix, key_system, "ENC-001-0")


def _sdoh_ctx() -> SimpleNamespace:
    return SimpleNamespace(
        record={
            "patient": {"patient_id": "POP-000002"},
            "encounters": [{"attending_physician_id": "STAFF-001", "admission_datetime": "2026-05-12T08:00:00"}],
            "care_level": "요介護1",  # any truthy value; downstream resolver may not care about the code value.
        },
        country="JP",
        roster_map={},
        hospital_config={},
        patient_data={
            "patient_id": "POP-000002",
            # >= social_history age_gates (Issue #938) so smoking / alcohol
            # Observations emit — the tests below assert their id / identifier
            # shape and would otherwise fail on the age gate returning [].
            "age": 50,
            "smoking_status": "never",
            "alcohol_use": "social",
            "blood_type": "A",
            "rh_factor": "+",
        },
        patient_id="POP-000002",
        primary_enc_id="ENC-001",
    )


def test_bb_smoking_status_id_is_opaque_with_identifier() -> None:
    ctx = _sdoh_ctx()
    resources = _bb_smoking_status(ctx)
    r = _find_by_prefix(resources, "smoking-")
    _assert_family_shape(r, "smoking-", SMOKING_STATUS_KEY_SYSTEM, "POP-000002")


def test_bb_alcohol_use_id_is_opaque_with_identifier() -> None:
    ctx = _sdoh_ctx()
    resources = _bb_alcohol_use(ctx)
    r = _find_by_prefix(resources, "alcohol-")
    _assert_family_shape(r, "alcohol-", ALCOHOL_USE_KEY_SYSTEM, "POP-000002")


def test_bb_blood_type_abo_and_rh_ids_are_opaque_with_identifier() -> None:
    ctx = _sdoh_ctx()
    resources = _bb_blood_type(ctx)
    abo = _find_by_prefix(resources, "blood-abo-")
    rh = _find_by_prefix(resources, "blood-rh-")
    _assert_family_shape(abo, "blood-abo-", BLOOD_ABO_KEY_SYSTEM, "POP-000002")
    _assert_family_shape(rh, "blood-rh-", BLOOD_RH_KEY_SYSTEM, "POP-000002")


def test_build_occupation_observation_id_is_opaque_with_identifier() -> None:
    r = _build_occupation_observation(occupation="engineer", patient_id="POP-000002", country="US")
    _assert_family_shape(r, "occupation-", OCCUPATION_KEY_SYSTEM, "POP-000002")


def test_bb_care_level_id_is_opaque_with_identifier() -> None:
    ctx = _sdoh_ctx()
    resources = _bb_care_level(ctx)
    r = _find_by_prefix(resources, "carelevel-")
    _assert_family_shape(r, "carelevel-", CARE_LEVEL_KEY_SYSTEM, "POP-000002")


def test_bb_code_status_id_is_opaque_with_identifier() -> None:
    ctx = SimpleNamespace(
        record={
            "code_status": "304253006",
            "encounters": [{"admission_datetime": "2026-05-12T08:00:00"}],
        },
        country="US",
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": "POP-000002"},
        patient_id="POP-000002",
        primary_enc_id="ENC-001",
    )
    resources = _bb_code_status(ctx)
    r = _find_by_prefix(resources, "codestatus-")
    _assert_family_shape(r, "codestatus-", CODE_STATUS_KEY_SYSTEM, "ENC-001")


# === Coverage guard — every id from a full-family in-process emit is opaque ===


def test_all_standalone_ids_from_in_process_emit_are_opaque() -> None:
    """Drives all 13 families' emitters and asserts every emitted id
    starting with one of the migrated prefixes matches its opaque
    pattern. Guards against a future emit-path addition that silently
    re-introduces a compound id."""
    resources: list[dict] = []
    resources.extend(_bb_nursing_observations(_nursing_ctx()))
    resources.extend(_bb_smoking_status(_sdoh_ctx()))
    resources.extend(_bb_alcohol_use(_sdoh_ctx()))
    resources.extend(_bb_blood_type(_sdoh_ctx()))
    resources.extend(_bb_care_level(_sdoh_ctx()))
    resources.append(_build_occupation_observation(occupation="engineer", patient_id="POP-000002", country="JP"))
    resources.extend(
        _bb_code_status(
            SimpleNamespace(
                record={"code_status": "304253006", "encounters": []},
                country="JP",
                roster_map={},
                hospital_config={},
                patient_data={"patient_id": "POP-000002"},
                patient_id="POP-000002",
                primary_enc_id="ENC-001",
            )
        )
    )

    non_opaque: list[str] = []
    for r in resources:
        rid = r.get("id", "")
        for prefix, pattern in _PATTERNS.items():
            if rid.startswith(prefix) and not pattern.match(rid):
                non_opaque.append(rid)
    assert not non_opaque, f"non-opaque stand-alone Observation.id leaked: {non_opaque[:5]}"
