"""Issue #360 G4: ClinicalImpression.description JP localization.

Pins the dual-slot ``description`` (EN, AD-30 canonical) +
``description_ja`` (JP, iris4h-ai UI display) shape on
``ClinicalImpressionRecord`` and the FHIR-emission-time locale switch.

Concrete failure this test guards
---------------------------------
Before the fix (commit ``8b85ed45``, 2026-07-20), JP output emitted:

    "description": "Day 5 of 16 inpatient clinical assessment
                    (severe) — acute phase. Attending review of vitals,
                    medication response, complication risk, and progress
                    toward discharge criteria."

The description reached the JP main physician's ClinicalImpression view
in English. Root cause: ``ClinicalImpressionRecord.description`` was
populated only in English at ``clinosim/modules/document/engine.py``,
and ``_build_clinical_impression`` had no locale-switching logic.

The fix populates both ``description`` and ``description_ja`` at engine
side (CIF stores both because the record does not carry the source
template parameters — sibling to
``EncounterConditionProtocol.chief_complaint_ja``); the FHIR builder
picks ``description_ja`` on JP output.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from clinosim.modules.output._fhir_clinical_impression import (
    CLINICAL_IMPRESSION_ID_PREFIX,
    _build_clinical_impression,
)
from clinosim.types.clinical import ClinicalImpressionRecord

pytestmark = pytest.mark.unit


def _record(**overrides: object) -> ClinicalImpressionRecord:
    """Build a minimal ClinicalImpressionRecord with defaults + overrides."""
    base = ClinicalImpressionRecord(
        impression_id=f"{CLINICAL_IMPRESSION_ID_PREFIX}enc-1-0",
        encounter_id="enc-1",
        date=date(2026, 6, 15),
        day_index=0,
        description="Day 1 of 3 inpatient clinical assessment — admission workup.",
        description_ja="入院第1病日／全3病日 臨床評価 — 入院時精査。",
        practitioner_id="dr-1",
    )
    return replace(base, **overrides) if overrides else base


# === Locale switch on FHIR emission ===


def test_jp_output_uses_japanese_description() -> None:
    """The Issue #360 G4 core assertion: ``ClinicalImpression.description``
    on JP output MUST equal the record's ``description_ja``."""
    rec = _record()
    res = _build_clinical_impression(rec, patient_id="pt-1", country="JP")
    assert res["description"] == "入院第1病日／全3病日 臨床評価 — 入院時精査。"


def test_us_output_uses_english_description() -> None:
    """US path must be unchanged (the ``description_ja`` field is present
    but ignored)."""
    rec = _record()
    res = _build_clinical_impression(rec, patient_id="pt-1", country="US")
    assert res["description"] == "Day 1 of 3 inpatient clinical assessment — admission workup."


def test_jp_output_falls_back_to_english_when_ja_missing() -> None:
    """Legacy records (created before the field existed) may have
    ``description_ja=""``. Fall back to the English string rather than
    emit an empty ``description`` — an empty description would be worse
    than an English one for a JP UI."""
    rec = _record(description_ja="")
    res = _build_clinical_impression(rec, patient_id="pt-1", country="JP")
    assert res["description"] == "Day 1 of 3 inpatient clinical assessment — admission workup."


def test_jp_output_falls_back_when_ja_field_absent_from_dict() -> None:
    """Defensive: a dict-shaped record (e.g. after JSON round-trip) that
    lacks ``description_ja`` altogether must fall back to English, not
    raise KeyError."""
    dict_rec = {
        "impression_id": f"{CLINICAL_IMPRESSION_ID_PREFIX}enc-1-0",
        "encounter_id": "enc-1",
        "date": date(2026, 6, 15),
        "description": "Day 1 EN description",
    }
    res = _build_clinical_impression(dict_rec, patient_id="pt-1", country="JP")
    assert res["description"] == "Day 1 EN description"


# === Description populated at document/engine.py ===


def test_jp_and_us_pick_different_descriptions_from_same_record() -> None:
    """End-to-end shape check: the same record emits ``description`` in
    Japanese vs English depending on ``ctx.country``. Confirms the FHIR
    builder is the only locale-switching site (record itself carries
    both strings, AD-30 CIF invariant preserved)."""
    rec = ClinicalImpressionRecord(
        impression_id=f"{CLINICAL_IMPRESSION_ID_PREFIX}enc-2-3",
        encounter_id="enc-2",
        date=date(2026, 6, 18),
        day_index=3,
        description="Day 4 of 10 inpatient clinical assessment for acute_mi (severe) — acute phase.",
        description_ja="入院第4病日／全10病日 臨床評価（acute_mi）（severe） — 急性期。",
        practitioner_id="dr-2",
    )
    jp = _build_clinical_impression(rec, patient_id="pt-2", country="JP")
    us = _build_clinical_impression(rec, patient_id="pt-2", country="US")
    assert "急性期" in jp["description"]
    assert "acute phase" in us["description"]
