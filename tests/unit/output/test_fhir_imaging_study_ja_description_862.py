"""ImagingStudy.description for stub-only studies (Issues #862, #2268).

CIF ``ImagingStudyRecord.description`` is an exam slug from disease-YAML
``- {test: "FAST_Ultrasound"}`` items when the body_sites-based procedure
lookup misses (Issue #822 stub-only branch). The description is the exam's
display name in the output language from the one imaging-exam table
(``clinosim.locale.loader.imaging_exam_display``), the same name the
narrative uses; no raw slug reaches FHIR.
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.locale.loader import imaging_exam_display, load_narrative_display_dict
from clinosim.modules.document.narrative._localization import _localize_imaging
from clinosim.modules.output.fhir_r4.labs.imaging_study import _build_imaging_study

pytestmark = pytest.mark.unit


def _stub_study(description: str) -> dict[str, Any]:
    """Minimal ImagingStudyRecord fixture that hits the stub-only branch."""
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


@pytest.mark.parametrize(
    ("slug", "ja"),
    [
        ("ECG", "心電図"),
        ("ECG_12lead", "12誘導心電図"),
        ("Echocardiography_TTE", "経胸壁心エコー"),
        ("FAST_Ultrasound", "FAST エコー (外傷)"),
        ("CT_Angiography_Chest_stat", "胸部 CT 血管造影 (緊急)"),
        ("MRCP", "MRCP (磁気共鳴胆管膵管撮影)"),
        ("Chest_Xray_PA_Lateral", "胸部レントゲン (正面・側面)"),
        ("ecg", "心電図"),
    ],
)
def test_fhir_and_narrative_use_the_same_name(slug: str, ja: str) -> None:
    assert imaging_exam_display(slug, "ja") == ja
    assert _build_imaging_study(_stub_study(slug), "ja")["description"] == ja
    assert _localize_imaging(slug, "ja") == ja


def test_us_description_is_the_english_display_not_the_slug() -> None:
    assert _build_imaging_study(_stub_study("FAST_Ultrasound"), "en")["description"] == "FAST ultrasound"


def test_unknown_exam_is_humanised_not_dropped() -> None:
    assert _build_imaging_study(_stub_study("Unknown_Exam"), "ja")["description"] == "Unknown Exam"


def test_exam_names_reach_the_shared_display_dict() -> None:
    ja_dict = load_narrative_display_dict()
    for cleaned in (
        "ecg",
        "echocardiogram",
        "ecg 12lead",
        "carotid ultrasound",
        "compression ultrasound lower extremity",
    ):
        assert cleaned in ja_dict, f"missing JA entry for {cleaned!r}"


def _protocol_imaging_names() -> set[str]:
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[3] / "clinosim" / "modules"
    names: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("imaging", "imaging_orders", "imaging_studies") and isinstance(v, list):
                    for item in v:
                        name = item.get("test") if isinstance(item, dict) else item
                        if isinstance(name, str):
                            names.add(name)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for path in sorted([*root.glob("disease/reference_data/*.yaml"), *root.glob("encounter/reference_data/*.yaml")]):
        walk(yaml.safe_load(path.read_text(encoding="utf-8")))
    return names


def test_every_protocol_imaging_exam_has_a_japanese_name() -> None:
    """Issue #2268: every imaging exam a protocol orders is in the one table
    (a humanised-slug fallback would leave English in JP output)."""
    import re

    missing = sorted(
        n for n in _protocol_imaging_names() if not re.search(r"[぀-ヿ一-鿿]", imaging_exam_display(n, "ja"))
    )
    assert not missing, missing
