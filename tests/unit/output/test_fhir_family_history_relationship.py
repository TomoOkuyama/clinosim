"""Issue #360 G2: FamilyMemberHistory.relationship CodeableConcept shape.

Pins the two-slot ``coding[].display`` (English canonical) + ``text``
(target language) pattern introduced by the iris4h-ai 2026-07-22
feedback fix chain.

Concrete failure this test guards
---------------------------------
Before the fix (commit ``8b85ed45``, 2026-07-20), JP output emitted:

    "relationship": {
      "coding": [
        {"system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
         "code": "FTH"}
      ]
    }

Neither ``coding[0].display`` nor ``text`` — the JP UI had no
human-readable label. Root cause: ``coding[0].display`` was set to the
Japanese string ("父"), which
``_strip_japanese_display_on_english_only_systems`` then stripped
because v3-RoleCode is treated as English-only (URI prefix
``http://terminology.hl7.org/``).

The fix routes English canonical into ``coding[0].display`` (survives
the strip walker) and the Japanese label into ``text`` (JP UI's source
of truth for human-readable content).
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.modules.output._fhir_family_history import _build_relationship_codeable

pytestmark = pytest.mark.unit


_FATHER_DISPLAYS: dict[str, str] = {"en": "Father", "ja": "父"}
_MOTHER_DISPLAYS: dict[str, str] = {"en": "Mother", "ja": "母"}
_SIBLING_DISPLAYS: dict[str, str] = {"en": "Sibling", "ja": "兄弟姉妹"}


# === JP output: coding.display = English canonical + text = Japanese ===


def test_jp_relationship_emits_english_display_and_japanese_text() -> None:
    """The Issue #360 G2 core assertion: JP output has ``coding[0].display``
    in English (survives the JP English-only-CS strip walker) AND ``text``
    in Japanese (source of truth for JP UI human-readable label)."""
    result = _build_relationship_codeable("FTH", _FATHER_DISPLAYS, "ja")
    assert result["coding"][0]["system"] == "http://terminology.hl7.org/CodeSystem/v3-RoleCode"
    assert result["coding"][0]["code"] == "FTH"
    assert result["coding"][0]["display"] == "Father"
    assert result["text"] == "父"


def test_jp_relationship_display_is_never_japanese() -> None:
    """Regression pin: no matter which relationship code is emitted, JP
    output never puts a Japanese string in ``coding[0].display`` (the
    strip walker would remove it, re-introducing the empty-label bug)."""
    for rel, disp in [
        ("FTH", _FATHER_DISPLAYS),
        ("MTH", _MOTHER_DISPLAYS),
        ("NSIB", _SIBLING_DISPLAYS),
    ]:
        result = _build_relationship_codeable(rel, disp, "ja")
        display = result["coding"][0]["display"]
        assert not any(ord(ch) > 0x7F for ch in display), (
            f"code {rel}: coding[0].display {display!r} contains non-ASCII "
            f"characters — would be stripped by "
            f"_strip_japanese_display_on_english_only_systems"
        )


def test_jp_relationship_text_is_japanese_for_known_codes() -> None:
    """The four common relationship codes (FTH/MTH/NSIB) MUST get a
    Japanese ``text``. Missing text is what the iris4h-ai UI had to
    dictionary-lookup around before this fix."""
    for rel, disp, expected_text in [
        ("FTH", _FATHER_DISPLAYS, "父"),
        ("MTH", _MOTHER_DISPLAYS, "母"),
        ("NSIB", _SIBLING_DISPLAYS, "兄弟姉妹"),
    ]:
        result = _build_relationship_codeable(rel, disp, "ja")
        assert result.get("text") == expected_text


# === US output: single English coding, no duplicated text ===


def test_us_relationship_omits_text_when_it_equals_english_display() -> None:
    """US output keeps the leaner two-field shape: coding[0].display carries
    the English string; ``text`` is omitted to avoid duplication (there is
    no target-language string that would add information)."""
    result = _build_relationship_codeable("FTH", _FATHER_DISPLAYS, "en")
    assert result["coding"][0]["display"] == "Father"
    assert "text" not in result


def test_us_relationship_still_has_valid_coding_shape() -> None:
    """Regression pin: US output must still carry the full FHIR coding
    (system + code + display) — the shape guarantees consumer parsing
    stays uniform across locales."""
    result = _build_relationship_codeable("MTH", _MOTHER_DISPLAYS, "en")
    coding = result["coding"][0]
    assert set(coding.keys()) == {"system", "code", "display"}
    assert coding["display"] == "Mother"


# === Defensive: missing English display / missing target-lang display ===


def test_relationship_falls_back_to_code_when_english_missing() -> None:
    """Defensive: if the reference data somehow omits the English display,
    fall back to the code itself rather than emitting a Japanese string
    into ``coding[0].display`` (which would then be stripped)."""
    disp_ja_only: dict[str, str] = {"ja": "父"}
    result = _build_relationship_codeable("FTH", disp_ja_only, "ja")
    assert result["coding"][0]["display"] == "FTH"
    assert result["text"] == "父"


def test_relationship_omits_text_when_target_lang_missing() -> None:
    """If the target-language string is missing, ``text`` is not emitted —
    consumers should render the English coding display instead of an
    empty ``text``."""
    disp_en_only: dict[str, str] = {"en": "Father"}
    result = _build_relationship_codeable("FTH", disp_en_only, "ja")
    assert result["coding"][0]["display"] == "Father"
    assert "text" not in result


# === End-to-end: builder output shape ===


def _build_one_fmh(country: str) -> dict[str, Any]:
    """Run ``_build_family_history`` on a minimal one-relative fixture and
    return the emitted FamilyMemberHistory resource."""
    from clinosim.modules.output._fhir_common import BundleContext
    from clinosim.modules.output._fhir_family_history import _build_family_history

    ctx = BundleContext(
        record={
            "family_history": [
                {
                    "relationship": "FTH",
                    "deceased": False,
                    "condition_codes": ["I25"],
                }
            ]
        },
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt-1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="",
    )
    result = _build_family_history(ctx)
    assert len(result) == 1
    return result[0]


def test_jp_fmh_relationship_has_english_display_and_japanese_text() -> None:
    """End-to-end pin: the JP FamilyMemberHistory FHIR resource emitted by
    ``_build_family_history`` carries the new two-slot relationship shape."""
    fmh = _build_one_fmh("JP")
    rel = fmh["relationship"]
    assert rel["coding"][0]["display"] == "Father"
    assert rel["text"] == "父"


def test_us_fmh_relationship_has_only_english_coding() -> None:
    fmh = _build_one_fmh("US")
    rel = fmh["relationship"]
    assert rel["coding"][0]["display"] == "Father"
    assert "text" not in rel
