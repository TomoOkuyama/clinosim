"""JP Condition MEDIS 病名管理番号 seed crosswalk (Issue #1277).

Pre-#1277 every JP Condition emitted the `99999999 未コード化傷病名`
placeholder in the `code.coding:medisRecordNo` slice — spec-compliant
but unusable for consumers doing JP DPC / claim analytics that key
on real MEDIS 病名管理番号.

Fix: seed ICD-10 → MEDIS 病名管理番号 crosswalk at
`codes/data/medis-disease-keyno.yaml`. Two 1:1 entries verified
2026-09-12 against fhir-jp-validator jpfhir-terminology 2.2606.0
`CodeSystem-medis-codesystem-diseasekanricodes` (fragment of MEDIS
5.18):

  E11.9 → 20050020  ２型糖尿病
  I50   → 20084004  うっ血性心不全

`_populate_condition_ai_mr_ecs_fields` in `post_process/populate.py`
consults the crosswalk on JP output; when an ICD-10 code in the
Condition's primary coding has a mapping the real MEDIS coding is
emitted, otherwise the `99999999` placeholder (pre-#1277 behaviour)
is preserved.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.post_process.populate import (
    _load_medis_crosswalk,
    _medis_crosswalk_lookup,
    _populate_condition_ai_mr_ecs_fields,
)

pytestmark = pytest.mark.unit

_ICD10_MHLW = "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full"
_MEDIS_URI = "http://medis.or.jp/CodeSystem/master-disease-keyNumber"


def _fresh_crosswalk() -> dict[str, tuple[str, str]]:
    _load_medis_crosswalk.cache_clear()
    return _load_medis_crosswalk()


def _condition(icd_code: str, display: str = "") -> dict:
    return {
        "resourceType": "Condition",
        "code": {"coding": [{"system": _ICD10_MHLW, "code": icd_code, "display": display}]},
    }


def _medis_coding(res: dict) -> dict | None:
    for c in (res.get("code") or {}).get("coding") or []:
        if isinstance(c, dict) and c.get("system") == _MEDIS_URI:
            return c
    return None


# ---------------------------------------------------------------------------
# Crosswalk loader
# ---------------------------------------------------------------------------


def test_crosswalk_yaml_loads_two_verified_seed_entries() -> None:
    """Seed crosswalk ships with exactly the 2 verified entries
    documented in the yaml header. New entries require per-code
    verification (see yaml file header for the extending workflow)."""
    xw = _fresh_crosswalk()
    assert set(xw.keys()) == {"E11.9", "I50"}, f"Seed crosswalk changed shape unexpectedly: {sorted(xw.keys())}"


def test_crosswalk_e11_9_maps_to_medis_20050020() -> None:
    xw = _fresh_crosswalk()
    assert xw["E11.9"] == ("20050020", "２型糖尿病")


def test_crosswalk_i50_maps_to_medis_20084004() -> None:
    xw = _fresh_crosswalk()
    assert xw["I50"] == ("20084004", "うっ血性心不全")


def test_lookup_falls_back_to_base_icd_when_specific_absent() -> None:
    """`I50.0` (subtype of I50) inherits the I50 mapping — the
    crosswalk registers the family via the base code."""
    assert _medis_crosswalk_lookup("I50.0") == ("20084004", "うっ血性心不全")


def test_lookup_returns_none_for_unmapped_icd() -> None:
    """I10 (essential HTN) is not in the fragment we verified against
    — no clean 1:1 match exists, so lookup returns None and the
    emit path falls back to `99999999`."""
    assert _medis_crosswalk_lookup("I10") is None


def test_lookup_returns_none_for_empty_input() -> None:
    assert _medis_crosswalk_lookup("") is None


# ---------------------------------------------------------------------------
# Emit-path integration
# ---------------------------------------------------------------------------


def test_jp_condition_e11_9_emits_medis_20050020() -> None:
    _load_medis_crosswalk.cache_clear()
    res = _condition("E11.9", "2型糖尿病")
    _populate_condition_ai_mr_ecs_fields(res, country="JP")
    medis = _medis_coding(res)
    assert medis is not None
    assert medis["code"] == "20050020"
    assert medis["display"] == "２型糖尿病"


def test_jp_condition_i50_emits_medis_20084004() -> None:
    _load_medis_crosswalk.cache_clear()
    res = _condition("I50", "心不全")
    _populate_condition_ai_mr_ecs_fields(res, country="JP")
    medis = _medis_coding(res)
    assert medis is not None
    assert medis["code"] == "20084004"


def test_jp_condition_i50_subtype_inherits_via_base_icd() -> None:
    """`I50.0` inherits the I50 mapping via the base-ICD fallback."""
    _load_medis_crosswalk.cache_clear()
    res = _condition("I50.0", "うっ血性心不全（急性）")
    _populate_condition_ai_mr_ecs_fields(res, country="JP")
    medis = _medis_coding(res)
    assert medis is not None
    assert medis["code"] == "20084004"


def test_jp_condition_i10_falls_back_to_99999999_placeholder() -> None:
    """Unmapped ICD → the pre-#1277 placeholder behaviour is preserved
    (spec-compliant JP-CLINS `medisRecordNo` slice)."""
    _load_medis_crosswalk.cache_clear()
    res = _condition("I10", "本態性高血圧症")
    _populate_condition_ai_mr_ecs_fields(res, country="JP")
    medis = _medis_coding(res)
    assert medis is not None
    assert medis["code"] == "99999999"
    assert medis["display"] == "未コード化傷病名"


def test_us_condition_never_gets_medis_coding_regression() -> None:
    """The MEDIS emit branch fires ONLY on JP output — US condition
    stays untouched (regression guard: crosswalk lookup must not
    accidentally add MEDIS coding to US emits)."""
    _load_medis_crosswalk.cache_clear()
    res = _condition("E11.9", "Type 2 Diabetes Mellitus")
    _populate_condition_ai_mr_ecs_fields(res, country="US")
    medis = _medis_coding(res)
    assert medis is None, "US emit must not carry MEDIS coding"


def test_populate_is_idempotent_for_existing_medis_coding() -> None:
    """If a Condition already carries a MEDIS coding (e.g. from an
    upstream mapper), the populate step is a no-op — no double
    coding, no overwrite."""
    _load_medis_crosswalk.cache_clear()
    res = _condition("E11.9", "2型糖尿病")
    res["code"]["coding"].append({"system": _MEDIS_URI, "code": "20100999", "display": "existing"})
    _populate_condition_ai_mr_ecs_fields(res, country="JP")
    medis_codings = [c for c in res["code"]["coding"] if c.get("system") == _MEDIS_URI]
    assert len(medis_codings) == 1
    assert medis_codings[0]["code"] == "20100999", "must not overwrite existing MEDIS coding"
