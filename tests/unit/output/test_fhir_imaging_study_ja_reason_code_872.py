"""Issue #872: ImagingStudy.reasonCode.text JA localization.

Pre-fix (iris4h-ai 2026-08-26 deploy verify): 3,608 / 4,735 (76.2 %) of JP
ImagingStudy resources with ``reasonCode`` shipped the English CIF
``Encounter.chief_complaint`` verbatim (e.g. ``"Sudden onset weakness, speech
difficulty, facial droop"``). The remaining 1,127 already localized to
Japanese because those encounters' disease YAMLs authored
``chief_complaint`` as a plain-JA string.

Fix (this PR): emit-time exact-match lookup at
``imaging_study.py::_bb_imaging_studies`` against ``_CHIEF_COMPLAINT_JA``
(30 entries covering every distinct EN vignette phrase observed on the
2026-08-26 deploy). Unknown values pass through unchanged so the 1,127
already-JA records are preserved as-is and future disease-YAML additions
degrade gracefully to the CIF text rather than a placeholder.

Longer-term the disease YAMLs should author ``chief_complaint: {en, ja}``
(dict form) so ``_disease_chief_complaint_ja`` populates
``Encounter.chief_complaint_ja`` and the emit path can prefer it; that
CIF-authoring work is deferred to a follow-on PR.
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.modules.output.fhir_r4.labs.imaging_study import (
    _CHIEF_COMPLAINT_JA,
    _bb_imaging_studies,
    _localize_chief_complaint,
)

pytestmark = pytest.mark.unit


# === _localize_chief_complaint predicate ===


@pytest.mark.parametrize(
    "en,ja",
    [
        ("Sudden onset weakness, speech difficulty, facial droop", "突然発症の脱力・構音障害・顔面麻痺"),
        ("Dyspnea on exertion, orthopnea, lower extremity edema", "労作時呼吸困難・起坐呼吸・下腿浮腫"),
        ("Fever, cough, dyspnea", "発熱・咳嗽・呼吸困難"),
        ("Chest pain, diaphoresis, dyspnea", "胸痛・発汗・呼吸困難"),
        ("Sudden severe headache, vomiting, altered consciousness", "突然の激しい頭痛・嘔吐・意識障害"),
        ("Right upper quadrant pain, fever, Murphy's sign positive", "右上腹部痛・発熱・Murphy徴候陽性"),
        ("Displaced distal radius fracture requiring ORIF", "ORIFを要する転位型橈骨遠位端骨折"),
    ],
)
def test_localize_chief_complaint_ja(en: str, ja: str) -> None:
    """Every EN vignette flagged by iris4h-ai 2026-08-26 verify resolves to
    the expected JA form."""
    assert _localize_chief_complaint(en, "ja") == ja


def test_localize_chief_complaint_en_passthrough() -> None:
    """US locale is a no-op — the pre-fix EN text is preserved."""
    en = "Sudden onset weakness, speech difficulty, facial droop"
    assert _localize_chief_complaint(en, "en") == en


def test_localize_chief_complaint_unknown_ja_passthrough() -> None:
    """Unknown EN phrase on JP locale passes through unchanged (silent-no-op
    fallback so a future disease-YAML EN vignette still emits)."""
    novel = "Some brand-new chief complaint not yet in dict"
    assert _localize_chief_complaint(novel, "ja") == novel


def test_localize_chief_complaint_already_ja_passthrough() -> None:
    """A chief complaint that is already Japanese (the 1,127 records already
    localized on the deploy) is NOT in ``_CHIEF_COMPLAINT_JA`` as a key and
    passes through unchanged — regression pin against a future dict entry
    that accidentally maps a JA input to something else."""
    ja_input = "労作時の呼吸困難と下腿浮腫"
    assert _localize_chief_complaint(ja_input, "ja") == ja_input


def test_localize_chief_complaint_empty_string() -> None:
    """Empty text short-circuits — the caller (``_bb_imaging_studies``)
    already guards on truthy ``_cc``, but the helper stays safe."""
    assert _localize_chief_complaint("", "ja") == ""
    assert _localize_chief_complaint("", "en") == ""


def test_all_30_iris4h_ai_2026_08_26_flagged_vignettes_covered() -> None:
    """Coverage guard: every distinct English chief-complaint vignette from
    the iris4h-ai 2026-08-26 deploy (JP p=10000 s500, 3,608 / 4,735 = 76.2%
    ImagingStudy.reasonCode.text leaked English) has an entry in
    ``_CHIEF_COMPLAINT_JA``. Detects a future accidental deletion."""
    iris4h_ai_2026_08_26_flagged = {
        "Sudden onset weakness, speech difficulty, facial droop",
        "Dyspnea on exertion, orthopnea, lower extremity edema",
        "Worsening dyspnea, increased sputum production, wheezing",
        "Fever, dysuria, flank pain",
        "Fever, cough, dyspnea",
        "Chest pain, diaphoresis, dyspnea",
        "Severe wheezing, dyspnea, use of accessory muscles",
        "Nausea, vomiting, abdominal pain, polyuria, altered consciousness",
        "Hip pain after fall, unable to walk",
        "High fever, myalgia, cough, fatigue",
        "Fever, altered mental status, hypotension",
        "Palpitations, dyspnea, dizziness, chest discomfort",
        "Acute dyspnea, pleuritic chest pain, tachycardia",
        "Fall from height at work site, multiple trauma",
        "Acute back pain after minimal trauma, worse with movement",
        "Severe epigastric pain radiating to back, nausea, vomiting",
        "Decreased urine output, edema, nausea, confusion",
        "Hematemesis, melena, dizziness, syncope",
        "Unilateral leg swelling, pain, warmth",
        "Sudden severe headache, vomiting, altered consciousness",
        "Cough, fever, dyspnea after witnessed aspiration event",
        "Displaced distal radius fracture requiring ORIF",
        "Right upper quadrant pain, fever, Murphy's sign positive",
        "Abdominal pain, vomiting, constipation, abdominal distension",
        "Erythema, warmth, swelling of affected limb, fever",
        "Major trauma, motor vehicle accident, multiple injuries",
        "Right lower quadrant pain, nausea, fever",
        "Industrial hand crush injury with possible amputation",
        "Abdominal distension, jaundice, confusion, hematemesis",
        "Altered consciousness after head trauma, progressive deterioration",
    }
    assert len(iris4h_ai_2026_08_26_flagged) == 30, (
        f"expected 30 distinct vignettes from deploy; got {len(iris4h_ai_2026_08_26_flagged)}"
    )
    missing = iris4h_ai_2026_08_26_flagged - _CHIEF_COMPLAINT_JA.keys()
    assert not missing, (
        f"EN vignettes flagged by iris4h-ai 2026-08-26 verify but missing from _CHIEF_COMPLAINT_JA: {sorted(missing)}"
    )


def test_no_dict_entry_is_still_english() -> None:
    """Guard against an accidentally-EN JA value in the dict — every mapped
    JA string must contain at least one Japanese character."""
    import re

    ja_char_re = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")
    offenders = [(en, ja) for en, ja in _CHIEF_COMPLAINT_JA.items() if not ja_char_re.search(ja)]
    assert not offenders, f"dict entries with no Japanese characters: {offenders}"


# === End-to-end via _bb_imaging_studies ===


def _ctx_with_encounter_cc(chief_complaint: str, country: str = "JP") -> Any:
    """Minimal BundleContext fixture with one encounter carrying the given
    chief_complaint, and one stub ImagingStudy in extensions."""
    from types import SimpleNamespace

    encounter = {
        "encounter_id": "ENC-1",
        "chief_complaint": chief_complaint,
    }
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
    record = {
        "encounters": [encounter],
        "extensions": {"imaging": [study]},
    }
    return SimpleNamespace(record=record, country=country)


def test_bb_imaging_studies_ja_localizes_flagged_en_chief_complaint() -> None:
    """Full emit path: an ImagingStudy tied to an encounter whose
    chief_complaint is one of the 30 flagged EN vignettes carries the JA
    text on ``reasonCode[0].text`` after this fix."""
    ctx = _ctx_with_encounter_cc(
        "Sudden onset weakness, speech difficulty, facial droop",
        country="JP",
    )
    studies = _bb_imaging_studies(ctx)
    assert len(studies) == 1
    assert studies[0]["reasonCode"][0]["text"] == "突然発症の脱力・構音障害・顔面麻痺"


def test_bb_imaging_studies_us_preserves_english() -> None:
    """US locale: the EN chief_complaint is emitted verbatim — regression pin."""
    en = "Sudden onset weakness, speech difficulty, facial droop"
    ctx = _ctx_with_encounter_cc(en, country="US")
    studies = _bb_imaging_studies(ctx)
    assert len(studies) == 1
    assert studies[0]["reasonCode"][0]["text"] == en


def test_bb_imaging_studies_ja_passthrough_already_ja_chief_complaint() -> None:
    """A chief_complaint already in JA (the 1,127-record subset from the
    deploy) is emitted verbatim on JP output — the fix must not corrupt
    them."""
    ja = "急性心筋梗塞疑いによる胸痛"
    ctx = _ctx_with_encounter_cc(ja, country="JP")
    studies = _bb_imaging_studies(ctx)
    assert len(studies) == 1
    assert studies[0]["reasonCode"][0]["text"] == ja


def test_bb_imaging_studies_ja_unknown_en_passes_through() -> None:
    """A novel EN chief_complaint (not in dict) is emitted as-is on JP
    output — silent-no-op fallback per the module docstring."""
    novel = "Novel presentation not yet in _CHIEF_COMPLAINT_JA"
    ctx = _ctx_with_encounter_cc(novel, country="JP")
    studies = _bb_imaging_studies(ctx)
    assert len(studies) == 1
    assert studies[0]["reasonCode"][0]["text"] == novel
