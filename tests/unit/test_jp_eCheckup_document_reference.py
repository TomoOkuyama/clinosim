"""P2-13 PR3 sub-PR-E(session 48):JP-eCheckup DocumentReference builder tests.

`_bb_document_references_checkup` は HEALTH_CHECKUP_REPORT の Composition と
併存する DocumentReference wrapper を emit する。scope:
- JP かつ health_checkup opt-in で emit される
- US または opt-in 無効時は emit しない(byte-diff invariant)
- Composition との参照(relatesTo transforms)
- LOINC 53576-5 + JP-eCheckup category
- narrative sections が populate されていれば content.attachment に反映
"""
from __future__ import annotations

import base64

import pytest


def _make_doc(**overrides):
    from clinosim.types.clinical import ClinicalDocument
    kwargs = {
        "document_id": "doc-CHK-POP-000001-001-01",
        "task_type": "health_checkup_report",
        "loinc_code": "53576-5",
        "patient_id": "POP-000001",
        "encounter_id": "CHK-POP-000001-001",
        "author_practitioner_id": "",
        "authored_datetime": "2026-06-30T11:00:00",
        "period_start": "2026-06-30T11:00:00",
        "period_end": "2026-06-30T11:00:00",
        "language": "ja",
        "format_type": "composition",
        "checkup_type": "occupational",
        "narrative": None,
    }
    kwargs.update(overrides)
    return ClinicalDocument(**kwargs)


def _make_ctx(record, country="JP"):
    """`BundleContext` を最小構成で作る。"""
    from clinosim.modules.output._fhir_common import BundleContext
    # record は dataclass だが builder は _o() で dict/attr 両対応、
    # 最小必要フィールドは record + country。builder は他フィールドを触らない。
    return BundleContext(
        record=record,
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="POP-000001",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="M",
    )


def _make_record(docs, patient_id="POP-000001"):
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile
    return CIFPatientRecord(
        patient=PatientProfile(patient_id=patient_id, age=55, sex="M"),
        documents=list(docs),
    )


def _make_narrative(text="健診結果:BMI 22.5、血圧 118/76、HbA1c 5.4%"):
    from clinosim.types.clinical import ClinicalDocumentNarrative
    return ClinicalDocumentNarrative(
        text=text,
        sections={"01031": text, "01032": "問診結果:既往なし"},
        facts_used=["ctx.lab_results"],
        generated_at="2026-06-30T11:05:00",
    )


@pytest.mark.unit
def test_no_emit_when_country_us():
    from clinosim.modules.output._fhir_document_reference_checkup import (
        _bb_document_references_checkup,
    )
    doc = _make_doc(narrative=_make_narrative())
    record = _make_record([doc])
    ctx = _make_ctx(record, country="US")
    assert _bb_document_references_checkup(ctx) == []


@pytest.mark.unit
def test_no_emit_when_task_type_not_checkup():
    from clinosim.modules.output._fhir_document_reference_checkup import (
        _bb_document_references_checkup,
    )
    doc = _make_doc(
        task_type="discharge_summary", loinc_code="18842-5",
        narrative=_make_narrative(),
    )
    record = _make_record([doc])
    ctx = _make_ctx(record)
    assert _bb_document_references_checkup(ctx) == []


@pytest.mark.unit
def test_no_emit_when_format_type_free_text():
    """free_text は既存 `_bb_document_references` が処理するので重複回避。"""
    from clinosim.modules.output._fhir_document_reference_checkup import (
        _bb_document_references_checkup,
    )
    doc = _make_doc(format_type="free_text", narrative=_make_narrative())
    record = _make_record([doc])
    ctx = _make_ctx(record)
    assert _bb_document_references_checkup(ctx) == []


@pytest.mark.unit
def test_skip_when_narrative_none():
    """Stage 2 未実行(narrative=None)は warn + skip、silent-no-op ではなく明示スキップ。"""
    from clinosim.modules.output._fhir_document_reference_checkup import (
        _bb_document_references_checkup,
    )
    doc = _make_doc(narrative=None)
    record = _make_record([doc])
    ctx = _make_ctx(record)
    assert _bb_document_references_checkup(ctx) == []


@pytest.mark.unit
def test_emit_docref_with_composition_relatesto():
    from clinosim.modules.output._fhir_document_reference_checkup import (
        _bb_document_references_checkup,
    )
    doc = _make_doc(narrative=_make_narrative())
    record = _make_record([doc])
    ctx = _make_ctx(record)
    resources = _bb_document_references_checkup(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "DocumentReference"
    # id は Composition と衝突しない prefix
    assert r["id"] == "drf-doc-CHK-POP-000001-001-01"
    assert r["status"] == "current"
    assert r["docStatus"] == "final"
    # type = LOINC 53576-5
    assert r["type"]["coding"][0]["code"] == "53576-5"
    # category = JP-eCheckup
    assert r["category"][0]["coding"][0]["code"] == "eCheckupGeneral"
    # relatesTo transforms → Composition
    assert r["relatesTo"] == [{
        "code": "transforms",
        "target": {"reference": "Composition/doc-CHK-POP-000001-001-01"},
    }]
    # encounter context
    assert r["context"]["encounter"][0]["reference"] == "Encounter/CHK-POP-000001-001"
    # subject
    assert r["subject"]["reference"] == "Patient/POP-000001"


@pytest.mark.unit
def test_content_attachment_contains_narrative_text():
    from clinosim.modules.output._fhir_document_reference_checkup import (
        _bb_document_references_checkup,
    )
    text = "健診結果:BMI 25.2、血圧 132/86、HbA1c 5.8%"
    doc = _make_doc(narrative=_make_narrative(text=text))
    record = _make_record([doc])
    ctx = _make_ctx(record)
    r = _bb_document_references_checkup(ctx)[0]
    attach = r["content"][0]["attachment"]
    decoded = base64.b64decode(attach["data"]).decode("utf-8")
    assert decoded == text
    assert attach["size"] == len(text.encode("utf-8"))
    assert attach["language"] == "ja"


@pytest.mark.unit
def test_fallback_to_sections_join_when_text_empty():
    """narrative.text が空でも sections 値を join して attachment を作れる。"""
    from clinosim.types.clinical import ClinicalDocumentNarrative
    from clinosim.modules.output._fhir_document_reference_checkup import (
        _bb_document_references_checkup,
    )
    narrative = ClinicalDocumentNarrative(
        text="",
        sections={"01031": "検査結果 A 判定", "01032": "問診 特記なし"},
        facts_used=[],
        generated_at="2026-06-30T11:05:00",
    )
    doc = _make_doc(narrative=narrative)
    record = _make_record([doc])
    ctx = _make_ctx(record)
    resources = _bb_document_references_checkup(ctx)
    assert len(resources) == 1
    attach = resources[0]["content"][0]["attachment"]
    decoded = base64.b64decode(attach["data"]).decode("utf-8")
    assert "検査結果 A 判定" in decoded
    assert "問診 特記なし" in decoded


@pytest.mark.unit
def test_custodian_set_and_masteridentifier_stable():
    from clinosim.modules.output._fhir_document_reference_checkup import (
        _bb_document_references_checkup,
    )
    doc = _make_doc(narrative=_make_narrative())
    record = _make_record([doc])
    r = _bb_document_references_checkup(_make_ctx(record))[0]
    assert r["custodian"] == {"reference": "Organization/hospital-main"}
    assert r["masterIdentifier"]["value"] == "drf-doc-CHK-POP-000001-001-01"
    assert r["identifier"][0]["value"] == "drf-doc-CHK-POP-000001-001-01"


@pytest.mark.unit
def test_registered_in_bundle_builders():
    """`_BUNDLE_BUILDERS` に登録済み(AD-56 registry)。"""
    from clinosim.modules.output.fhir_r4_adapter import available_builders
    assert "_bb_document_references_checkup" in available_builders()
