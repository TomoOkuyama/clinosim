"""Issue #862: ImagingStudy.description JA localization for stub-only studies.

CIF ``ImagingStudyRecord.description`` is populated from disease-YAML
``- {test: "FAST_Ultrasound"}`` items when the body_sites-based procedure
lookup misses (Issue #822 stub-only branch). Pre-fix behavior: 22.4% of
ImagingStudy resources (1,060 / 4,735 in the JP p=10000 s500 sample)
shipped that raw English string as ``.description`` on JP output.

Fix: normalize underscores to spaces, look up the JA form in the shared
``drug_names_ja.yaml`` (new "Imaging exam names" section), pass through
on US and on any unknown key.
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.locale.loader import load_drug_names_ja
from clinosim.modules.output.fhir_r4.labs.imaging_study import (
    _build_imaging_study,
    _localize_imaging_exam_name,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_drug_names_ja_cache() -> None:
    """Ensure each test sees the current drug_names_ja.yaml (this PR edits it)."""
    load_drug_names_ja.cache_clear()


def _stub_study(description: str) -> dict[str, Any]:
    """Minimal ImagingStudyRecord fixture that hits the stub-only branch
    (Issue #822 fallback) at labs/imaging_study.py:240.

    - No `body_site_snomed` → body_sites lookup misses → primary path skipped.
    - No `modality_code` → modality array empty.
    - `description` is the field being localized.
    """
    return {
        "study_id": "imgst-ENC-TEST-0",
        "study_instance_uid": "2.25.1234567890",
        "encounter_id": "ENC-TEST",
        "patient_id": "POP-TEST",
        "order_id": "ORD-TEST",
        "status": "available",
        "started_datetime": "2026-05-06T08:41:00+09:00",
        "modality_code": "",
        "body_site_snomed": "",
        "description": description,
        "series": [],
    }


# === _localize_imaging_exam_name (unit — direct helper) ===


def test_localize_ecg() -> None:
    assert _localize_imaging_exam_name("ECG") == "心電図"


def test_localize_ecg_12lead_underscore_normalizes_to_space() -> None:
    """Underscore form matches the space-keyed yaml entry."""
    assert _localize_imaging_exam_name("ECG_12lead") == "12誘導心電図"


def test_localize_echocardiography_tte() -> None:
    assert _localize_imaging_exam_name("Echocardiography_TTE") == "経胸壁心エコー"


def test_localize_fast_ultrasound() -> None:
    assert _localize_imaging_exam_name("FAST_Ultrasound") == "FAST超音波(外傷救急)"


def test_localize_multi_word_ct_angiography_chest_stat() -> None:
    """Longest-form key (5 tokens including modifier) resolves."""
    assert _localize_imaging_exam_name("CT_Angiography_Chest_stat") == "胸部CT血管造影(緊急)"


def test_localize_mrcp_acronym_only() -> None:
    assert _localize_imaging_exam_name("MRCP") == "MRCP(磁気共鳴胆管膵管撮影)"


def test_localize_unknown_exam_passes_through() -> None:
    """Unknown keys return the original English form (graceful degradation)."""
    assert _localize_imaging_exam_name("Some_Novel_Exam") == "Some_Novel_Exam"


def test_localize_case_insensitive() -> None:
    """Loader lowercases yaml keys, so case in the input doesn't matter."""
    assert _localize_imaging_exam_name("ecg") == "心電図"


# === _build_imaging_study end-to-end (JP path) ===


def test_stub_only_jp_description_is_ja() -> None:
    """The full emit path with a stub-only study produces JA .description on JP output."""
    res = _build_imaging_study(_stub_study("FAST_Ultrasound"), "ja")
    assert res["description"] == "FAST超音波(外傷救急)"


def test_stub_only_us_description_is_english() -> None:
    """US output must NOT localize — the English form is the correct surface."""
    res = _build_imaging_study(_stub_study("FAST_Ultrasound"), "en")
    assert res["description"] == "FAST_Ultrasound"


def test_stub_only_jp_ecg_end_to_end() -> None:
    """Top-volume offender (218 records) end-to-end."""
    res = _build_imaging_study(_stub_study("ECG"), "ja")
    assert res["description"] == "心電図"


def test_stub_only_jp_unknown_exam_passes_through_on_emit() -> None:
    """Even in JP output, unknown-key exams still emit (as English) — the emit
    site never silently drops the description."""
    res = _build_imaging_study(_stub_study("Unknown_Exam"), "ja")
    assert res["description"] == "Unknown_Exam"


# === drug_names_ja.yaml integrity (Issue #862 section covers all 34 exam kinds) ===


def test_drug_names_ja_covers_all_issue_862_top_15() -> None:
    """Every top-15 English exam name has a JA entry in the yaml.

    The 15 cover 991 / 1060 records (93.5%). The remaining 19 tail entries
    are also covered by the yaml (see other tests) but the top-15 gate
    catches regressions on the highest-volume kinds first.
    """
    ja_dict = load_drug_names_ja()
    for cleaned in (
        "ecg",
        "echocardiogram",
        "ecg 12lead",
        "echocardiography tte",
        "carotid ultrasound",
        "ankle xray",
        "echocardiography",
        "coronary angiography",
        "bladder ultrasound",
        "ct angiography",
        "slit lamp exam",
        "fluorescein stain",
        "echocardiography bedside",
        "ct angiography chest",
        "compression ultrasound lower extremity",
    ):
        assert cleaned in ja_dict, f"missing JA entry for {cleaned!r}"
