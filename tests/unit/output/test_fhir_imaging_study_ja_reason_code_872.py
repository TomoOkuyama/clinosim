"""ImagingStudy.reasonCode.text is the encounter's chief complaint in the
output language (Issues #872, #2461).

The text comes from the encounter itself: ``chief_complaint_<lang>`` (filled
from the disease protocol's ``chief_complaint: {en, ja}`` map), else the
English ``chief_complaint``. There is no second translation table keyed by
the English sentence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import clinosim
from clinosim.modules.output.fhir_r4.labs.imaging_study import _bb_imaging_studies

pytestmark = pytest.mark.unit


def _ctx(chief_complaint: str, chief_complaint_ja: str = "", country: str = "JP") -> Any:
    """Minimal BundleContext with one encounter and one stub ImagingStudy."""
    from types import SimpleNamespace

    encounter = {"encounter_id": "ENC-1", "chief_complaint": chief_complaint}
    if chief_complaint_ja:
        encounter["chief_complaint_ja"] = chief_complaint_ja
    study = SimpleNamespace(
        study_id="imgst-1",
        study_instance_uid="1.2.3.4",
        encounter_id="ENC-1",
        patient_id="POP-1",
        order_id="ORD-1",
        status="available",
        started_datetime="2026-06-15T09:00:00",
        modality_code="",
        body_site_snomed="",
        series=[],
        endpoint_id="",
        contrast=False,
        report=None,
    )
    return SimpleNamespace(record={"encounters": [encounter], "extensions": {"imaging": [study]}}, country=country)


def _reason_text(ctx: Any) -> str:
    studies = _bb_imaging_studies(ctx)
    assert len(studies) == 1
    return studies[0]["reasonCode"][0]["text"]


def test_jp_uses_the_encounter_japanese_chief_complaint() -> None:
    en = "Sudden onset weakness, speech difficulty, facial droop"
    ja = "突然の片麻痺・構音障害・顔面麻痺"
    assert _reason_text(_ctx(en, ja)) == ja


def test_us_uses_the_english_chief_complaint() -> None:
    en = "Sudden onset weakness, speech difficulty, facial droop"
    assert _reason_text(_ctx(en, "突然の片麻痺・構音障害・顔面麻痺", country="US")) == en


def test_jp_without_a_japanese_entry_falls_back_to_english() -> None:
    en = "Novel presentation"
    assert _reason_text(_ctx(en)) == en


def test_no_chief_complaint_translation_table() -> None:
    root = Path(clinosim.__file__).parent
    assert not (root / "locale" / "shared" / "chief_complaint_translations.yaml").exists()
