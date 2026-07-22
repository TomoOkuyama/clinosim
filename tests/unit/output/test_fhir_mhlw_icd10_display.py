"""Issue #358: MHLW ICD-10 Japanese-only display alignment.

Pins two related invariants introduced by the v19 → v20 fix chain:

1. ``_build_diagnosis_codeable_concept`` does NOT emit an English secondary
   coding when the primary system is a Japanese-only registry
   (``icd-10-mhlw``). MHLW's ICD-10 2013 registry publishes only a Japanese
   display per concept, so an English display against the same system URI
   can never match the authoritative CS at conformance time.
2. The four C-series cancer codes emitted by FamilyMemberHistory
   (C18/C34/C50/C61) carry MHLW-canonical Japanese displays — ``及び`` (not
   ``および``) and the ``＜腫瘍＞`` suffix required by the MHLW registry.

Concrete failure this test guards
---------------------------------
v19 validation (2026-07-22, JP p=1000 seed=300, master ``39ae1b7f``)
reported 378 errors, all on ``FamilyMemberHistory.condition.code.coding[]``:

    coding[0]: display="気管支および肺の悪性新生物"  (JA mismatch with MHLW)
    coding[1]: display="Malignant neoplasm of bronchus and lung"  (EN on JA-only CS)

Both fixes together bring FMH display errors 378 → 0.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.codes.loader import is_japanese_only_display_system
from clinosim.modules.output._fhir_common import _build_diagnosis_codeable_concept

pytestmark = pytest.mark.unit


# === is_japanese_only_display_system predicate ===


def test_icd10_mhlw_is_marked_japanese_only() -> None:
    """MHLW ICD-10 2013 registry has Japanese-only displays — the archetypal
    case Issue #358 exists to handle."""
    assert is_japanese_only_display_system("icd-10-mhlw") is True


def test_icd10_and_icd10_cm_are_not_japanese_only() -> None:
    """WHO ICD-10 and CM are English-first registries; adding them here would
    silently drop English coding worldwide — the check must stay tight."""
    assert is_japanese_only_display_system("icd-10") is False
    assert is_japanese_only_display_system("icd-10-cm") is False


def test_unknown_system_is_not_japanese_only() -> None:
    """Unknown keys default to False (safe default: emit English coding as
    before, no silent behavior change for new callers)."""
    assert is_japanese_only_display_system("some-future-system") is False
    assert is_japanese_only_display_system("") is False


# === _build_diagnosis_codeable_concept: JP-only CS emits single Japanese coding ===


def test_jp_diagnosis_mhlw_emits_only_japanese_coding() -> None:
    """The Issue #358 core assertion: JP diagnosis CodeableConcept for MHLW
    ICD-10 has exactly ONE coding entry (Japanese display only). Emitting a
    second English coding against the same MHLW URI is what produced the
    v19 189 English-display validator errors."""
    cc = _build_diagnosis_codeable_concept("C34", "icd-10-mhlw", "JP")
    assert len(cc["coding"]) == 1
    coding = cc["coding"][0]
    assert coding["system"] == "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/ICD10-2013-full"
    assert coding["code"] == "C34"
    # Japanese display must be present, non-empty, and NOT an English string
    assert coding["display"]
    assert coding["display"] != "Malignant neoplasm of bronchus and lung"


def test_jp_diagnosis_mhlw_never_emits_english_display_against_jp_uri() -> None:
    """Regression pin: even for a code where the Japanese display would
    differ meaningfully from English, no English coding leaks in."""
    for code in ("C18", "C34", "C50", "C61"):
        cc = _build_diagnosis_codeable_concept(code, "icd-10-mhlw", "JP")
        displays = [c["display"] for c in cc["coding"]]
        for d in displays:
            # None of the displays should contain ASCII letters (a Japanese
            # display is 100% CJK / punctuation for these codes).
            assert not any(ch.isascii() and ch.isalpha() for ch in d), (
                f"code {code}: coding.display {d!r} contains English letters — violates Issue #358 JP-only rule"
            )


def test_us_diagnosis_icd10cm_still_emits_english_only() -> None:
    """Regression pin: US path (primary_lang=en) always emitted a single
    English coding; Issue #358 must not affect US behaviour."""
    cc = _build_diagnosis_codeable_concept("C34", "icd-10-cm", "US")
    assert len(cc["coding"]) == 1
    assert cc["coding"][0]["system"] == "http://hl7.org/fhir/sid/icd-10-cm"


def test_jp_diagnosis_non_mhlw_system_still_emits_english_secondary() -> None:
    """Regression pin: the JP-only skip is scoped to the whitelisted systems.
    A hypothetical JP path using a non-Japanese-only CS (e.g. WHO
    ``icd-10``) still gets the English secondary coding for interop —
    Issue #358 explicitly does not change that path."""
    cc = _build_diagnosis_codeable_concept("C34", "icd-10", "JP")
    # Should have 2 coding entries: Japanese primary + English secondary,
    # because "icd-10" is NOT in the Japanese-only whitelist.
    assert len(cc["coding"]) == 2
    displays = [c["display"] for c in cc["coding"]]
    # At least one is Japanese (contains CJK) and at least one is English
    # (contains ASCII letters).
    assert any(any(ch.isascii() and ch.isalpha() for ch in d) for d in displays)
    assert any(any(ord(ch) > 0x7F for ch in d) for d in displays)


# === MHLW-canonical Japanese displays for the four C-series cancer codes ===


@pytest.mark.parametrize(
    "code,expected_ja",
    [
        ("C18", "結腸の悪性新生物＜腫瘍＞"),
        ("C34", "気管支及び肺の悪性新生物＜腫瘍＞"),
        ("C50", "乳房の悪性新生物＜腫瘍＞"),
        ("C61", "前立腺の悪性新生物＜腫瘍＞"),
    ],
)
def test_cancer_c_series_ja_display_matches_mhlw_canonical(code: str, expected_ja: str) -> None:
    """Pin the exact MHLW canonical Japanese display for each of the four
    C-series cancer codes emitted by FamilyMemberHistory. Any drift
    (「および」→「及び」regression, missing ``＜腫瘍＞`` suffix) re-introduces
    the v19 189 Japanese-display validator errors."""
    assert code_lookup("icd-10", code, "ja") == expected_ja
    # Same via the MHLW alias (shares data via _SYSTEM_DATA_ALIASES).
    assert code_lookup("icd-10-mhlw", code, "ja") == expected_ja


def test_cancer_c_series_uses_kyuji_kanji_and_tumor_suffix() -> None:
    """Structural guard: every C-series family-history cancer display uses
    ``及び`` (never ``および``) and ends with ``＜腫瘍＞``. Catches future
    regressions where a display update reverts to the pre-MHLW form."""
    for code in ("C18", "C34", "C50", "C61"):
        display = code_lookup("icd-10-mhlw", code, "ja")
        assert "および" not in display, (
            f"code {code}: display {display!r} uses hiragana ``および``, MHLW canonical requires kanji ``及び``"
        )
        assert display.endswith("＜腫瘍＞"), (
            f"code {code}: display {display!r} missing MHLW-required "
            f"``＜腫瘍＞`` suffix on C-series (malignant neoplasm)"
        )


# === Round-trip through _build_diagnosis_codeable_concept ===


@pytest.mark.parametrize(
    "code,expected_ja",
    [
        ("C18", "結腸の悪性新生物＜腫瘍＞"),
        ("C34", "気管支及び肺の悪性新生物＜腫瘍＞"),
        ("C50", "乳房の悪性新生物＜腫瘍＞"),
        ("C61", "前立腺の悪性新生物＜腫瘍＞"),
    ],
)
def test_mhlw_codeable_concept_carries_canonical_display(code: str, expected_ja: str) -> None:
    """End-to-end: the same MHLW canonical display reaches ``coding[0].display``
    when a JP FamilyMemberHistory FHIR builder calls
    ``_build_diagnosis_codeable_concept``. This is the surface the v19
    validator inspects."""
    cc = _build_diagnosis_codeable_concept(code, "icd-10-mhlw", "JP")
    assert cc["coding"][0]["display"] == expected_ja
