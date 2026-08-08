"""JP_Patient_eCS assertion + data-completeness guards (Issue #378, restoring
after #382 hotfix).

## History
* PR #379 (session 65) added `JP_Patient_eCS` URI — but Patient data didn't
  emit the profile's min=1 requirements (`name.text`, `address.text`,
  `meta.lastUpdated`). Result: 5× cascade in v26 (~30k additional validator
  errors — every Patient failed eCS validation, and every referring resource
  inherited the failure).
* PR #382 (session 66) reverted the URI to stop the bleeding.
* Session 80 Issue #378 restores the URI WITH the required fields emitted,
  closing the original Pattern B (3,096 errors on referring eCS resources)
  without the earlier cascade.

## What this file guards
1. JP output declares BOTH `JP_Patient` (JP Core) AND `JP_Patient_eCS`.
2. The eCS min=1 data fields are populated: `meta.lastUpdated`,
   `name.text`, `address.text` (verified against the eCS SD differential —
   removing any of them re-opens the #382 cascade risk).
3. US output continues to omit `meta.profile` entirely (no US Core profile
   is asserted — that's a separate roadmap item; the JP-side changes must
   not accidentally leak).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import _build_patient

pytestmark = pytest.mark.unit

_JP_PATIENT = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient"
_JP_PATIENT_ECS = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Patient_eCS"


def _sample_p() -> dict:
    return {
        "patient_id": "pt-1",
        "name": {"family_name": "田中", "given_name": "太郎"},
        "sex": "M",
        "date_of_birth": "1970-01-01",
        "address": {
            "state": "東京都",
            "city": "千代田区",
            "line1": "丸の内 1-1-1",
            "postal_code": "100-0005",
            "country": "JP",
        },
    }


def test_jp_patient_meta_profile_carries_both_jp_core_and_ecs() -> None:
    """Issue #378: JP output declares JP_Patient (Core) + JP_Patient_eCS (eCS).
    The dual assertion resolves v25 Pattern B (referring eCS resources now
    have a Patient that conforms to the eCS profile they require)."""
    p = _build_patient(_sample_p(), country="JP")
    profiles = p.get("meta", {}).get("profile", [])
    assert _JP_PATIENT in profiles, f"JP_Patient (Core) missing: {profiles}"
    assert _JP_PATIENT_ECS in profiles, f"JP_Patient_eCS missing: {profiles}"


def test_jp_patient_meta_last_updated_is_populated() -> None:
    """Issue #378 data-completeness: JP_Patient_eCS requires
    `meta.lastUpdated` (min=1). Missing this field re-opens the v26 cascade
    that PR #382 reverted."""
    p = _build_patient(_sample_p(), country="JP")
    meta = p.get("meta", {})
    assert meta.get("lastUpdated"), f"meta.lastUpdated missing on JP Patient: {meta}"


def test_jp_patient_name_carries_text() -> None:
    """Issue #378 data-completeness: JP_Patient_eCS requires `name.text`
    (min=1)."""
    p = _build_patient(_sample_p(), country="JP")
    names = p.get("name", [])
    assert names, "JP Patient must have at least one name entry"
    for n in names:
        assert n.get("text"), f"name.text missing on JP Patient name: {n}"


def test_jp_patient_address_carries_text() -> None:
    """Issue #378 data-completeness: JP_Patient_eCS requires `address.text`
    (min=1)."""
    p = _build_patient(_sample_p(), country="JP")
    addresses = p.get("address", [])
    assert addresses, "JP Patient must have at least one address entry"
    for a in addresses:
        assert a.get("text"), f"address.text missing on JP Patient address: {a}"


def test_us_patient_omits_meta_profile_entirely() -> None:
    """US export intentionally omits meta.profile (no US Core profile is
    asserted — a separate roadmap item). The JP-side #378 changes must NOT
    accidentally add meta.profile to US output."""
    p = _build_patient(_sample_p(), country="US")
    assert "meta" not in p or "profile" not in p.get("meta", {}), f"US Patient carries meta.profile: {p.get('meta')}"


def test_us_patient_address_omits_text() -> None:
    """Issue #378: `address.text` addition is JP-only (avoids US byte-diff
    on Patient.address). US Address should NOT carry `text`."""
    us_patient = dict(_sample_p())
    us_patient["address"] = {"line1": "123 Main St", "city": "Boston", "country": "US"}
    p = _build_patient(us_patient, country="US")
    for a in p.get("address", []):
        assert "text" not in a, f"US Patient.address unexpectedly carries text: {a}"
