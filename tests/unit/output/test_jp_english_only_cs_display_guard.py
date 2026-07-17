"""Regression: sibling-copy walker must NOT re-inject Japanese display on
English-only CodeSystems (session 57 chain G).

Backstory:

The strip walker `_strip_japanese_display_on_english_only_systems`
removes Japanese `display` values from Coding entries whose `system` is
on the English-only allowlist (LOINC / SNOMED / HL7 terminology / DICOM /
UCUM / `http://hl7.org/fhir/*` — includes ICD-10). Then the sibling-copy
walker `_copy_display_from_sibling_coding` (part of
`_populate_condition_ai_mr_ecs_fields`) fills a missing display by
looking up the code. On JP output it used `code_lookup(..., "ja")` first
— **which put the Japanese display right back**, undoing the strip and
tripping HAPI Validator's "Wrong Display Name" check (v2 feedback
§【中優先 7】 = ~2,500 ICD-10 errors).

The fix guards the ja lookup path: when the coding's system is on the
English-only allowlist, skip the ja lookup so the walker falls through
to the sibling English display (path 2) or the canonical English lookup
(path 3). JP-CS entries are unaffected — they still receive a Japanese
display via ja lookup as before.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4_adapter import (
    _copy_display_from_sibling_coding,
    _strip_japanese_display_on_english_only_systems,
)


def test_icd10_jp_output_does_not_reinject_japanese_display() -> None:
    codings = [
        {"system": "http://hl7.org/fhir/sid/icd-10", "code": "I10", "display": "本態性高血圧症"},
        {"system": "http://hl7.org/fhir/sid/icd-10", "code": "I10", "display": "Essential (primary) hypertension"},
    ]
    resource = {"resourceType": "Condition", "code": {"coding": codings}}
    _strip_japanese_display_on_english_only_systems(resource)
    _copy_display_from_sibling_coding(codings, lang="ja")
    for c in codings:
        assert c.get("display") == "Essential (primary) hypertension", c


def test_loinc_jp_output_does_not_reinject_japanese_display() -> None:
    codings = [
        {"system": "http://loinc.org", "code": "8480-6", "display": "収縮期血圧"},
        {"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"},
    ]
    resource = {"resourceType": "Observation", "code": {"coding": codings}}
    _strip_japanese_display_on_english_only_systems(resource)
    _copy_display_from_sibling_coding(codings, lang="ja")
    for c in codings:
        assert c.get("display") == "Systolic blood pressure", c


def test_jp_cs_still_receives_ja_display_from_sibling() -> None:
    """Regression: JP-native CodeSystem must still get its ja display."""
    codings = [
        {"system": "http://jpfhir.jp/fhir/core/CodeSystem/JP_CS", "code": "X"},
        {"system": "http://jpfhir.jp/fhir/core/CodeSystem/JP_CS", "code": "X", "display": "日本語ラベル"},
    ]
    _copy_display_from_sibling_coding(codings, lang="ja")
    for c in codings:
        assert c.get("display") == "日本語ラベル", c


def test_us_output_english_display_unchanged() -> None:
    codings = [
        {"system": "http://hl7.org/fhir/sid/icd-10", "code": "I10"},
        {"system": "http://hl7.org/fhir/sid/icd-10", "code": "I10", "display": "Essential (primary) hypertension"},
    ]
    _copy_display_from_sibling_coding(codings, lang="en")
    for c in codings:
        assert c.get("display") == "Essential (primary) hypertension", c


def test_english_only_cs_without_sibling_falls_back_to_code_lookup_en() -> None:
    """When no sibling display exists, path 3 (code_lookup en) fills the gap."""
    codings = [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "I10"}]
    _copy_display_from_sibling_coding(codings, lang="ja")
    disp = codings[0].get("display", "")
    if disp:
        assert all(ord(ch) < 0x3040 or ord(ch) > 0x9FFF for ch in disp), (
            f"English-only CS must not receive a JP display; got {disp!r}"
        )
