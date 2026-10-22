"""Phase 3.γ — OMB race / ethnicity authority catalog externalisation.

The pre-fix module-local dicts in
``fhir_r4/demographics/patient.py``:
    _OMB_RACE_CODE_DISPLAY: dict[str, tuple[str, str]]  # 6 entries
    _OMB_ETHNICITY_CODE_DISPLAY: dict[str, tuple[str, str]]  # 2 entries
duplicated authority code + display information for the CDC
race+ethnicity CodeSystem (OID 2.16.840.1.113883.6.238). The audit
flagged them as the Phase 3 Orange violation — no equivalent
authority yaml existed in ``clinosim/codes/data/`` and extending the
sim to a new locale forced an EN+code → EN edit inside Python.

Phase 3.γ ships two new authority yamls (``omb-race.yaml`` +
``omb-ethnicity.yaml``) with EN + JA displays per code. The module-
local dicts now carry only the clinosim-internal slug → OMB code
mapping (6 + 2 entries); display is pulled from the authority via
``code_lookup("omb-race" | "omb-ethnicity", code, lang)``.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.codes.loader import _load_system
from clinosim.modules.output.fhir_r4.demographics import patient as patient_mod

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# The pre-fix (slug → (code, display)) dict shape is retired.
# ---------------------------------------------------------------------------


def test_retired_omb_display_dicts_absent_from_patient_module():
    """Re-introducing a tuple-shaped (code, display) dict fails here."""
    for sym in ("_OMB_RACE_CODE_DISPLAY", "_OMB_ETHNICITY_CODE_DISPLAY"):
        assert not hasattr(patient_mod, sym), (
            f"{sym} must be retired — display lives in codes/data/omb-*.yaml, only the slug→code map remains inline."
        )


# ---------------------------------------------------------------------------
# The slim slug → code dicts stay.
# ---------------------------------------------------------------------------


def test_slug_to_code_dicts_preserved_without_display_column():
    assert hasattr(patient_mod, "_OMB_RACE_SLUG_TO_CODE")
    assert hasattr(patient_mod, "_OMB_ETHNICITY_SLUG_TO_CODE")
    # Every slug maps to a str code (not a tuple).
    for slug, code in patient_mod._OMB_RACE_SLUG_TO_CODE.items():
        assert isinstance(code, str) and code, f"race slug {slug!r} must map to str code"
    for slug, code in patient_mod._OMB_ETHNICITY_SLUG_TO_CODE.items():
        assert isinstance(code, str) and code, f"ethnicity slug {slug!r} must map to str code"


# ---------------------------------------------------------------------------
# Both new authority yamls load + carry every code the slug map points at.
# ---------------------------------------------------------------------------


def test_omb_race_authority_yaml_loads():
    r = _load_system("omb-race")
    assert r is not None, "codes/data/omb-race.yaml must load via the standard loader"
    assert r.uri == "urn:oid:2.16.840.1.113883.6.238"
    assert len(r.codes) == 6


def test_omb_ethnicity_authority_yaml_loads():
    r = _load_system("omb-ethnicity")
    assert r is not None
    assert r.uri == "urn:oid:2.16.840.1.113883.6.238"
    assert len(r.codes) == 2


@pytest.mark.parametrize(
    "slug,code,expected_en",
    [
        ("white", "2106-3", "White"),
        ("black", "2054-5", "Black or African American"),
        ("asian", "2028-9", "Asian"),
        ("native_american", "1002-5", "American Indian or Alaska Native"),
        ("pacific_islander", "2076-8", "Native Hawaiian or Other Pacific Islander"),
        ("other", "2131-1", "Other Race"),
    ],
)
def test_race_code_resolves_to_expected_display(slug: str, code: str, expected_en: str):
    """Every slug→code pointer must resolve to the canonical OMB
    EN display via the authority yaml."""
    assert patient_mod._OMB_RACE_SLUG_TO_CODE[slug] == code
    assert code_lookup("omb-race", code, "en") == expected_en


@pytest.mark.parametrize(
    "slug,code,expected_en",
    [
        ("hispanic", "2135-2", "Hispanic or Latino"),
        ("not_hispanic", "2186-5", "Not Hispanic or Latino"),
    ],
)
def test_ethnicity_code_resolves_to_expected_display(slug: str, code: str, expected_en: str):
    assert patient_mod._OMB_ETHNICITY_SLUG_TO_CODE[slug] == code
    assert code_lookup("omb-ethnicity", code, "en") == expected_en


# ---------------------------------------------------------------------------
# JA displays emerge from the authority yaml — a Phase 3.γ side effect.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "system_key,code",
    [
        ("omb-race", "2106-3"),
        ("omb-race", "2054-5"),
        ("omb-race", "2028-9"),
        ("omb-race", "1002-5"),
        ("omb-race", "2076-8"),
        ("omb-race", "2131-1"),
        ("omb-ethnicity", "2135-2"),
        ("omb-ethnicity", "2186-5"),
    ],
)
def test_ja_display_available_for_every_omb_code(system_key: str, code: str):
    """A JA display is now available for every OMB code (would allow
    a future JP-locale extension emit, not currently used because
    us-core-race/ethnicity is US-only)."""
    ja = code_lookup(system_key, code, "ja")
    assert ja and ja != code, f"ja display missing for {system_key}:{code}"


# ---------------------------------------------------------------------------
# End-to-end: _build_us_core_race_extension emits the catalog display.
# ---------------------------------------------------------------------------


def test_build_us_core_race_extension_uses_catalog_display():
    ext = patient_mod._build_us_core_race_extension("white")
    assert ext is not None
    omb_cat = next(e for e in ext["extension"] if e["url"] == "ombCategory")
    assert omb_cat["valueCoding"]["code"] == "2106-3"
    assert omb_cat["valueCoding"]["display"] == "White"
    text = next(e for e in ext["extension"] if e["url"] == "text")
    assert text["valueString"] == "White"


def test_build_us_core_race_extension_unknown_slug_returns_none():
    assert patient_mod._build_us_core_race_extension("") is None
    assert patient_mod._build_us_core_race_extension("klingon") is None


def test_build_us_core_ethnicity_extension_uses_catalog_display():
    ext = patient_mod._build_us_core_ethnicity_extension("hispanic")
    assert ext is not None
    omb_cat = next(e for e in ext["extension"] if e["url"] == "ombCategory")
    assert omb_cat["valueCoding"]["code"] == "2135-2"
    assert omb_cat["valueCoding"]["display"] == "Hispanic or Latino"


# ---------------------------------------------------------------------------
# Lang parameter wiring — passing lang="ja" renders JA display.
# ---------------------------------------------------------------------------


def test_build_us_core_race_extension_lang_ja_renders_ja_display():
    """Phase 3.γ adds a ``lang`` parameter. Passing ``lang="ja"`` surfaces
    the JA display from the authority yaml — a side-effect improvement
    over the pre-fix dict which was EN-only."""
    ext = patient_mod._build_us_core_race_extension("asian", lang="ja")
    omb_cat = next(e for e in ext["extension"] if e["url"] == "ombCategory")
    assert omb_cat["valueCoding"]["display"] == "アジア系"
