"""Regression guard for Issue #382 (session 66 hotfix reverting #379).

PR #379 added `JP_Patient_eCS` to `Patient.meta.profile` expecting to
resolve v25 Pattern B (3,096 errors on referring eCS resources). But
Patient data does not yet emit the eCS profile's required identifier
slices / extensions — the URI-only assertion caused a 5× cascade
regression in v26 (~30k additional errors as every Patient failed eCS
validation, and every resource referencing a Patient inherited the
failure). Issue #382 hotfix reverts to JP_Patient only.

This test now guards the OPPOSITE invariant: `JP_Patient_eCS` MUST NOT
appear on `Patient.meta.profile` unless the accompanying data emit is
also implemented (Option B follow-up chain). Re-adding the URI without
the data → immediate re-regression.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output._fhir_patient import _build_patient

pytestmark = pytest.mark.unit

_JP_PATIENT = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient"
_JP_PATIENT_ECS = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Patient_eCS"


def _sample_p() -> dict:
    return {
        "patient_id": "pt-1",
        "family_name_kanji": "田中",
        "given_name_kanji": "太郎",
        "family_name_kana": "タナカ",
        "given_name_kana": "タロウ",
        "sex": "male",
        "birthdate": "1970-01-01",
    }


def test_jp_patient_meta_profile_carries_jp_core_only() -> None:
    """JP output declares JP_Patient (JP Core) on meta.profile."""
    p = _build_patient(_sample_p(), country="JP")
    profiles = p.get("meta", {}).get("profile", [])
    assert profiles == [_JP_PATIENT], f"unexpected meta.profile: {profiles}"


def test_jp_patient_must_not_declare_ecs_without_data_completeness() -> None:
    """Regression guard for Issue #382: JP_Patient_eCS MUST NOT be
    asserted on Patient.meta.profile until the accompanying data-emit
    changes are implemented (Option B follow-up). Re-adding this URI
    without emitting the eCS profile's required identifier slices /
    extensions caused ~30k cascade errors in v26 — every Patient failed
    eCS validation and every referring resource inherited the failure."""
    p = _build_patient(_sample_p(), country="JP")
    profiles = p.get("meta", {}).get("profile", [])
    assert _JP_PATIENT_ECS not in profiles, (
        f"JP_Patient_eCS re-declared on Patient.meta.profile without eCS "
        f"data-completeness. This causes ~30k cascade validator errors "
        f"(v26 regression, Issue #382). See _fhir_patient.py comment + "
        f"Issue #382 follow-up plan (Option B) before re-adding."
    )


def test_us_patient_omits_meta_profile_entirely() -> None:
    """US export intentionally omits meta.profile (no US Core profile is
    asserted — a separate roadmap item). Regression pin: the JP-side
    revert must NOT accidentally add meta.profile to US output."""
    p = _build_patient(_sample_p(), country="US")
    assert "meta" not in p or "profile" not in p.get("meta", {}), (
        f"US Patient carries meta.profile: {p.get('meta')}"
    )
