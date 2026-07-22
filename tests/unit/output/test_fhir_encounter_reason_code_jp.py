"""Issue #360 G1: Encounter.reasonCode.text JP fallback.

Pins the JP-locale fallback of Encounter.reasonCode.text to the
JP-stashed ``chief_complaint_ja`` field on the CIF encounter, so JP
output never leaks the English chief-complaint string to the JP
Clinical Cockpit UI when ICD-10 code_lookup cannot resolve a Japanese
display (either the code is empty, or resolves to itself).

Concrete failure this test guards
---------------------------------
Before the fix (commit ``8b85ed45``, 2026-07-20), JP output emitted:

    "reasonCode": [
      {"text": "Dyspnea on exertion, orthopnea, lower extremity edema"}
    ]

The English chief-complaint string from
``heart_failure_exacerbation.yaml`` reached the JP main-physician
receiving-history view. Root cause: CIF stores ``chief_complaint`` in
English (AD-30 canonical); the FHIR emitter fell back to that string
when ICD-10 code_lookup could not resolve a Japanese display.

The fix (a) adds ``Encounter.chief_complaint_ja`` populated at
encounter creation from the disease/encounter protocol's ``ja`` entry,
and (b) makes ``_fhir_encounter._build_encounter`` prefer the JP field
on the fallback path.
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.modules.output._fhir_encounter import _build_encounter

pytestmark = pytest.mark.unit


def _enc(
    chief_en: str = "Dyspnea on exertion, orthopnea, lower extremity edema",
    chief_ja: str = "",
    admit_dx_code: str = "",
) -> dict[str, Any]:
    """Minimal encounter dict for FHIR-emitter unit test."""
    return {
        "encounter_id": "ENC-POP-000018-305936649034-ED",
        "patient_id": "pt-1",
        "encounter_type": "emergency",
        "status": "finished",
        "admission_datetime": "2026-06-15T22:00:00+09:00",
        "discharge_datetime": "2026-06-15T23:30:00+09:00",
        "chief_complaint": chief_en,
        "chief_complaint_ja": chief_ja,
        "admit_dx_code": admit_dx_code,
    }


def _build_and_reason_text(enc: dict[str, Any], country: str) -> str:
    """Run ``_build_encounter`` and return ``reasonCode[0].text``."""
    res = _build_encounter(
        enc,
        patient_id="pt-1",
        country=country,
        admit_dx_code=enc.get("admit_dx_code", ""),
        primary_dx_code="",
    )
    rc = res.get("reasonCode") or []
    return rc[0].get("text", "") if rc else ""


# === JP fallback path (no code / unresolvable code) ===


def test_jp_encounter_uses_chief_complaint_ja_when_no_admit_dx_code() -> None:
    """The Issue #360 G1 core assertion: JP output picks
    ``chief_complaint_ja`` on the fallback path (empty admit_dx_code)
    rather than the English ``chief_complaint``."""
    enc = _enc(chief_ja="労作時呼吸困難・起座呼吸・下肢浮腫")
    reason_text = _build_and_reason_text(enc, "JP")
    assert reason_text == "労作時呼吸困難・起座呼吸・下肢浮腫"
    assert "Dyspnea" not in reason_text


def test_jp_encounter_falls_back_to_english_when_ja_field_empty() -> None:
    """Legacy encounters (pre-fix) have ``chief_complaint_ja=""``. Fall
    back to English rather than emit an empty reasonCode.text — an empty
    text would fail JP UI rendering and lose semantic content."""
    enc = _enc(chief_ja="")
    reason_text = _build_and_reason_text(enc, "JP")
    assert reason_text == "Dyspnea on exertion, orthopnea, lower extremity edema"


def test_jp_encounter_falls_back_when_ja_field_absent_from_dict() -> None:
    """Defensive: a legacy dict-shape encounter that lacks
    ``chief_complaint_ja`` altogether must fall back to English rather
    than raise KeyError."""
    enc = _enc()
    del enc["chief_complaint_ja"]
    reason_text = _build_and_reason_text(enc, "JP")
    assert reason_text == "Dyspnea on exertion, orthopnea, lower extremity edema"


# === US path unchanged ===


def test_us_encounter_ignores_chief_complaint_ja() -> None:
    """Regression pin: US output must NOT pick up ``chief_complaint_ja``
    even when populated — leaves US behaviour unchanged."""
    enc = _enc(chief_ja="労作時呼吸困難")
    reason_text = _build_and_reason_text(enc, "US")
    assert reason_text == "Dyspnea on exertion, orthopnea, lower extremity edema"


# === JP path with resolvable ICD-10 code (should NOT fall back) ===


def test_jp_encounter_uses_icd10_display_when_code_resolvable() -> None:
    """When ICD-10 code_lookup resolves a Japanese display (e.g. I50.9 →
    "心不全、詳細不明"), that display wins over ``chief_complaint_ja`` —
    the coded display is authoritative and matches JP Core / MHLW's
    canonical."""
    enc = _enc(chief_ja="労作時呼吸困難", admit_dx_code="I50.9")
    reason_text = _build_and_reason_text(enc, "JP")
    # code_lookup("icd-10-mhlw", "I50.9", "ja") = "心不全、詳細不明"
    assert reason_text == "心不全、詳細不明"


# === _disease_chief_complaint_ja helper ===


def test_disease_chief_complaint_ja_returns_ja_when_present() -> None:
    """The helper reads ``protocol.chief_complaint["ja"]`` when a per-
    language dict is present."""
    from types import SimpleNamespace

    from clinosim.simulator.helpers import _disease_chief_complaint_ja

    proto = SimpleNamespace(chief_complaint={"en": "Dyspnea", "ja": "呼吸困難"})
    assert _disease_chief_complaint_ja(proto) == "呼吸困難"


def test_disease_chief_complaint_ja_returns_empty_when_plain_string() -> None:
    """A plain-string ``chief_complaint`` (no per-language dict) has no
    JP entry — the helper returns "" so the caller leaves the encounter
    field empty (emitter falls back to English)."""
    from types import SimpleNamespace

    from clinosim.simulator.helpers import _disease_chief_complaint_ja

    proto = SimpleNamespace(chief_complaint="Dyspnea only in English")
    assert _disease_chief_complaint_ja(proto) == ""


def test_disease_chief_complaint_ja_returns_empty_when_ja_missing() -> None:
    """A dict-form ``chief_complaint`` with no ``ja`` key — the helper
    returns "" rather than the English fallback (would defeat the split
    purpose by stashing English in the JA field)."""
    from types import SimpleNamespace

    from clinosim.simulator.helpers import _disease_chief_complaint_ja

    proto = SimpleNamespace(chief_complaint={"en": "Dyspnea"})
    assert _disease_chief_complaint_ja(proto) == ""
