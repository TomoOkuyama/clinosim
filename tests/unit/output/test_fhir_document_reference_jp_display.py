"""Issue #360 G5: DocumentReference.type carries EN LOINC display + JP text.

Pins the two-slot ``coding[].display`` (English LOINC canonical, survives
the JP English-only-CS strip walker) + ``text`` (Japanese, primary UI
label) pattern on ``DocumentReference.type`` — sibling of the G2 fix
applied to FamilyMemberHistory.relationship.

Concrete failure this test guards
---------------------------------
Before the fix (commit ``8b85ed45``, 2026-07-20), JP output emitted:

    "type": {
      "coding": [
        {"system": "http://loinc.org", "code": "11506-3", "display": null}
      ]
    }

The ``coding[].display`` was populated with Japanese ("経過記録"), which
``_strip_japanese_display_on_english_only_systems`` (walker in
fhir_r4_adapter.py) then stripped because LOINC is treated as an
English-only CS. Some LOINC codes (e.g. 34133-9) were missing from
``codes/data/loinc.yaml`` altogether, producing an outright empty
display AND empty text.

The fix (a) adds the missing 34133-9 code, and (b) emits English
canonical to ``coding[].display`` (walker-safe) and Japanese to
``text`` (walker-safe, UI's source of truth).
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.modules.output.fhir_r4.documents.documents import _build_dref_from_clinical_doc

pytestmark = pytest.mark.unit


def _doc_stub(loinc: str) -> dict[str, Any]:
    return {
        "document_id": f"doc-enc-1-{loinc}",
        "loinc_code": loinc,
        "task_type": "progress_note",
        "encounter_id": "enc-1",
        "language": "",  # let country resolve
        "content_type": "text/plain",
        "author_practitioner_id": "dr-1",
        "period_start": "2026-06-15T09:00:00+09:00",
        "period_end": "2026-06-15T09:00:00+09:00",
        "authored_datetime": "2026-06-15T09:00:00+09:00",
    }


def _narr(text: str = "Sample progress note text.") -> dict[str, Any]:
    return {"text": text}


# === EN LOINC display goes to coding, JP goes to text ===


@pytest.mark.parametrize(
    "loinc,expected_en,expected_ja",
    [
        # Issue #369: LOINC canonical LONG_COMMON_NAME (ja lookup requires it).
        ("11506-3", "Provider-unspecified Progress note", "経過記録"),
        ("18842-5", "Discharge summary note", "退院時サマリー"),
        ("34117-2", "History and physical note", "入院時記録"),
        # 34133-9 was missing from loinc.yaml pre-fix; adding it here is
        # part of this PR (data + emitter both change).
        ("34133-9", "Summary of episode note", "サマリー文書"),
    ],
)
def test_jp_dref_type_has_en_coding_display_and_jp_text(loinc: str, expected_en: str, expected_ja: str) -> None:
    """The Issue #360 G5 core assertion: JP output has EN LOINC canonical on
    ``coding[].display`` (survives the strip walker) AND JP on ``text``
    (UI's source of truth)."""
    res = _build_dref_from_clinical_doc(_doc_stub(loinc), _narr(), patient_id="pt-1", country="JP")
    assert res is not None
    coding = res["type"]["coding"][0]
    assert coding["code"] == loinc
    assert coding["display"] == expected_en
    assert res["type"]["text"] == expected_ja


def test_us_dref_type_has_en_coding_display_and_en_text() -> None:
    """US path: text is English (same as coding.display) — leaner shape
    unchanged from pre-fix behaviour."""
    res = _build_dref_from_clinical_doc(_doc_stub("11506-3"), _narr(), patient_id="pt-1", country="US")
    assert res is not None
    # Issue #369: LOINC canonical LONG_COMMON_NAME (also used on US path
    # for consistency; SHORTNAME "Progress note" is not the CS canonical).
    assert res["type"]["coding"][0]["display"] == "Provider-unspecified Progress note"
    assert res["type"]["text"] == "Provider-unspecified Progress note"


def test_missing_loinc_falls_back_to_code_on_both_slots() -> None:
    """Defensive: an unknown LOINC code (not in loinc.yaml) falls back to
    the code itself on both display slots rather than emitting an empty
    string that would fail JP UI rendering."""
    res = _build_dref_from_clinical_doc(_doc_stub("99999-9"), _narr(), patient_id="pt-1", country="JP")
    assert res is not None
    assert res["type"]["coding"][0]["display"] == "99999-9"
    assert res["type"]["text"] == "99999-9"


# === Missing-code regression pin: 34133-9 must be resolvable ===


def test_loinc_34133_9_is_resolvable_in_both_locales() -> None:
    """Regression pin: LOINC 34133-9 was missing from codes/data/loinc.yaml
    before this PR — the display fell back to the numeric code on any
    ClinicalDocument that used the ``summary_of_episode`` role. Guards
    against a future accidental deletion."""
    assert code_lookup("loinc", "34133-9", "en") == "Summary of episode note"
    assert code_lookup("loinc", "34133-9", "ja") == "サマリー文書"


# === Attachment content unaffected ===


def test_attachment_data_still_base64_encoded_regardless_of_locale() -> None:
    """Non-regression pin: the display-only fix does not touch the
    attachment payload path. ``content.attachment.data`` must be
    base64-encoded UTF-8 as before."""
    res = _build_dref_from_clinical_doc(_doc_stub("11506-3"), _narr("Hello 日本"), patient_id="pt-1", country="JP")
    assert res is not None
    data_b64 = res["content"][0]["attachment"]["data"]
    assert base64.b64decode(data_b64).decode("utf-8") == "Hello 日本"


# === session-88j P2-4: DocumentReference.description snippet ===


def test_description_populated_with_first_non_empty_line() -> None:
    """P2-4: description carries the first non-empty line of the narrative
    body so consumers can distinguish sibling documents of the same type
    in list views (before this fix, `.description` was null on every
    DocumentReference and the UI could show only type + date)."""
    body = "本日、経過安定。バイタルサイン正常。\n次行は無視される。"
    res = _build_dref_from_clinical_doc(_doc_stub("11506-3"), _narr(body), patient_id="pt-1", country="JP")
    assert res is not None
    assert res.get("description") == "本日、経過安定。バイタルサイン正常。"


def test_description_capped_at_100_chars() -> None:
    """P2-4: description is a list-view snippet, not the full body — must
    not exceed 100 chars (attachment.data still carries the full text)."""
    long_line = "あ" * 200  # 200-char Japanese
    res = _build_dref_from_clinical_doc(_doc_stub("11506-3"), _narr(long_line), patient_id="pt-1", country="JP")
    assert res is not None
    assert len(res["description"]) == 100
    assert res["description"] == "あ" * 100


def test_description_skips_leading_blank_lines() -> None:
    """P2-4: leading blank / whitespace-only lines don't become the
    description — the first line with content wins."""
    body = "\n\n   \n実際の記録内容はここから始まる。\n他行。"
    res = _build_dref_from_clinical_doc(_doc_stub("11506-3"), _narr(body), patient_id="pt-1", country="JP")
    assert res is not None
    assert res["description"] == "実際の記録内容はここから始まる。"


def test_description_omitted_when_body_is_whitespace_only() -> None:
    """P2-4: an all-whitespace body should not emit a stub description.
    (In practice the outer builder short-circuits to None on empty text,
    so this pins the invariant that we never emit `description: ""`.)"""
    # A body with only whitespace triggers the outer `if not text: return None`
    # guard, so the resource itself is None — description never appears.
    res = _build_dref_from_clinical_doc(_doc_stub("11506-3"), _narr("   \n\n   "), patient_id="pt-1", country="JP")
    # Either None (short-circuit) or a resource whose description is absent —
    # both are acceptable; the invariant is that we never emit a blank string.
    if res is not None:
        assert "description" not in res or res["description"]


def test_description_attachment_data_independence() -> None:
    """P2-4: the full body still lives verbatim in attachment.data
    (base64) — description is additive, not a replacement."""
    body = "先頭行の要約。\n二行目以降に本文の詳細が続く。\n三行目もある。"
    res = _build_dref_from_clinical_doc(_doc_stub("11506-3"), _narr(body), patient_id="pt-1", country="JP")
    assert res is not None
    # description has only the first line
    assert res["description"] == "先頭行の要約。"
    # attachment.data still carries the full body
    decoded = base64.b64decode(res["content"][0]["attachment"]["data"]).decode("utf-8")
    assert decoded == body
