"""The radiology conclusionCode agrees with the read (Issue #3676)."""

from __future__ import annotations

import pytest

from clinosim.modules.imaging.engine import (
    imaging_template_read_is_abnormal,
    load_body_sites,
    load_impression_templates,
)
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _imaging_conclusion_code

pytestmark = pytest.mark.unit

NORMAL = "17621005"
ABNORMAL = "263654008"


def _code(entry: dict) -> str:
    return entry["coding"][0]["code"]


def _site_snomed(site_key: str) -> str | None:
    return (load_body_sites().get(site_key) or {}).get("snomed")


def _all_reads():
    """(modality, body-site snomed, text, lang, expected abnormal) of every template text."""
    for bucket_by_key in load_impression_templates().values():
        for key, bucket in bucket_by_key.items():
            modality, _, site = key.partition("_")
            snomed = _site_snomed(site)
            if snomed is None:
                continue
            variants = []
            if "normal" in bucket:
                variants.append((bucket["normal"], False))
            if "abnormal" in bucket:
                variants.append((bucket["abnormal"], True))
            for entry in (bucket.get("abnormal_by_code") or {}).values():
                if isinstance(entry, dict):
                    variants.append((entry, True))
                else:
                    pass
            for variant, abnormal in variants:
                imp = variant["impression"]
                for lang in ("en", "ja"):
                    yield (
                        modality,
                        snomed,
                        imp[lang].replace("{side}", "右" if lang == "ja" else "right"),
                        lang,
                        abnormal,
                    )


def test_pneumonia_read_is_abnormal_in_both_languages() -> None:
    chest = _site_snomed("chest")
    assert (
        _code(_imaging_conclusion_code("CR", chest, "Right lower lobe pneumonia with surrounding inflammation.", "en"))
        == ABNORMAL
    )
    assert _code(_imaging_conclusion_code("CR", chest, "右下葉肺炎像。", "ja")) == ABNORMAL


def test_normal_read_is_normal_in_both_languages() -> None:
    chest = _site_snomed("chest")
    assert _code(_imaging_conclusion_code("CR", chest, "No acute pulmonary process.", "en")) == NORMAL
    assert _code(_imaging_conclusion_code("CR", chest, "急性肺疾患を示唆する所見なし。", "ja")) == NORMAL


def test_a_report_without_a_template_falls_back_to_the_keywords() -> None:
    assert _code(_imaging_conclusion_code("CR", "", "Displaced fracture of the distal radius.", "en")) == ABNORMAL
    assert _code(_imaging_conclusion_code("CR", "", "No acute findings.", "en")) == NORMAL
    assert _code(_imaging_conclusion_code("CR", "", "", "en")) == NORMAL


def test_every_template_read_gets_the_code_of_its_own_variant() -> None:
    reads = list(_all_reads())
    assert len(reads) > 100
    wrong = [
        (m, text)
        for m, snomed, text, lang, abnormal in reads
        if (_code(_imaging_conclusion_code(m, snomed, text, lang)) == ABNORMAL) != abnormal
    ]
    assert wrong == []


def test_template_decision_is_unknown_for_an_untemplated_text() -> None:
    assert imaging_template_read_is_abnormal("CR", _site_snomed("chest"), ("Something never templated.",)) is None
