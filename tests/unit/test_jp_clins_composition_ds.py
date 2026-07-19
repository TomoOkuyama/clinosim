"""P2-13 PR2a Task 4:JP-CLINS 退院時サマリー Composition unit tests(JP-only)."""

from __future__ import annotations

import pytest

_PROFILE_URL = "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary"
_DOC_TYPE_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/document-section"


def _jp_ds_doc():
    return {
        "document_id": "doc-ENC-001-01",
        "document_type": "DISCHARGE_SUMMARY",
        "loinc_code": "18842-5",
        "format_type": "composition",
        "patient_id": "POP-000001",
        "encounter_id": "ENC-001",
        "author_practitioner_id": "PRAC-JP-001",
        "authored_datetime": "2026-01-20T10:00:00",
        "language": "ja",
        "period_start": "2026-01-15T09:00:00",
        "period_end": "2026-01-20T10:00:00",
        "narrative": {
            "sections": {
                # Admission side (5)
                "admission_reason": "細菌性肺炎のため入院となった。",
                "admission_details": "2026-01-15、救急外来受診後、内科病棟に入院した。",
                "admission_diagnoses": "1. 細菌性肺炎（J13）",
                "chief_complaint": "発熱・咳嗽",
                "present_illness": "3日前より発熱と咳嗽を認め、当院受診となった。",
                # Discharge side (5, session 59 #286)
                "hospital_course": "抗菌薬治療により経過良好、5 日間の入院で改善。",
                "discharge_details": "2026-01-20、内科病棟から自宅退院となった。",
                "discharge_diagnoses": "1. 細菌性肺炎（J13）",
                "discharge_medications": "アモキシシリン 500mg 1日3回 × 7日間",
                "discharge_instructions": "十分な休養と水分摂取を心がけてください。",
            }
        },
    }


def _us_ds_doc():
    return {
        "document_id": "doc-ENC-101-01",
        "document_type": "DISCHARGE_SUMMARY",
        "loinc_code": "18842-5",
        "format_type": "composition",
        "patient_id": "POP-000002",
        "encounter_id": "ENC-101",
        "author_practitioner_id": "PRAC-US-001",
        "authored_datetime": "2026-01-20T10:00:00",
        "language": "en",
        "period_start": "2026-01-15T09:00:00",
        "period_end": "2026-01-20T10:00:00",
        "narrative": {
            "sections": {
                "admission_summary": "Admitted for bacterial pneumonia.",
                "hospital_course": "Improved on ceftriaxone.",
                "discharge_diagnoses": "1. Bacterial pneumonia (J13)",
                "discharge_medications": "amoxicillin-clavulanate 500mg PO TID x7d",
                "discharge_instructions": "Follow up in 1 week.",
                "follow_up": "PCP in 7 days",
            }
        },
    }


@pytest.mark.unit
def test_jp_clins_composition_type_uses_doc_typecodes():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    assert any(c.get("system") == _DOC_TYPE_SYSTEM and c.get("code") == "18842-5" for c in comp["type"]["coding"]), (
        comp["type"]
    )


@pytest.mark.unit
def test_jp_clins_composition_has_profile():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    profs = comp.get("meta", {}).get("profile", [])
    assert _PROFILE_URL in profs


@pytest.mark.unit
def test_jp_clins_composition_has_nested_structural_section():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    top = comp["section"]
    # Session 58 Chain #9: exactly one top-level section (300 構造情報セクション)
    # that nests the 10 required child slices (5 admission + 5 discharge)
    # per JP-CLINS eDS spec `structuredSection.section` min=10.
    assert len(top) == 1, top
    parent = top[0]
    parent_code = parent["code"]["coding"][0]
    assert parent_code["system"] == _SECTION_SYSTEM
    assert parent_code["code"] == "300"
    children = parent["section"]
    child_codes = {c["code"]["coding"][0]["code"] for c in children}
    assert child_codes == {
        # Admission (5)
        "312",  # reasonForAdmissionSection
        "322",  # detailsOnAdmissionSection
        "342",  # diagnosesOnAdmissionSection
        "352",  # chiefComplaintsSection
        "360",  # presentIllnessSection
        # Discharge (5) — Chain #9 additions
        "333",  # hospitalCourseSection
        "324",  # detailsOnDischargeSection
        "344",  # diagnosesOnDischargeSection
        "444",  # medicationOnDischargeSection
        "424",  # instructionOnDischargeSection
    }


@pytest.mark.unit
def test_jp_clins_composition_child_section_text_div():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    parent = comp["section"][0]
    children_by_code = {c["code"]["coding"][0]["code"]: c for c in parent["section"]}
    # 312 = admission_reason
    assert "細菌性肺炎" in children_by_code["312"]["text"]["div"]
    # 352 = chief_complaint
    assert "発熱" in children_by_code["352"]["text"]["div"]
    # 360 = present_illness
    assert "3日前" in children_by_code["360"]["text"]["div"]


@pytest.mark.unit
def test_jp_clins_composition_section_title_short_display_long():
    """Session 58 Chain #8/#9: JP-CLINS eDS spec pins
    `section.title` = short form (no `セクション` suffix, spec `title.fixedString`)
    and `section.code.coding.display` = long form (`patternString`,
    ends in `セクション`)."""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    parent = comp["section"][0]
    assert parent["title"] == "構造情報"
    assert parent["code"]["coding"][0]["display"] == "構造情報セクション"
    expected = {
        "312": ("入院理由", "入院理由セクション"),
        "322": ("入院時詳細", "入院時詳細セクション"),
        "342": ("入院時診断", "入院時診断セクション"),
        "352": ("主訴", "主訴セクション"),
        "360": ("現病歴", "現病歴セクション"),
        "333": ("入院中経過", "入院中経過セクション"),
        "324": ("退院時詳細", "退院時詳細セクション"),
        "344": ("退院時診断", "退院時診断セクション"),
        "444": ("退院時投薬指示", "退院時投薬指示セクション"),
        "424": ("退院時方針指示", "退院時方針指示セクション"),
    }
    for child in parent["section"]:
        code = child["code"]["coding"][0]["code"]
        assert code in expected, f"unexpected child section code {code!r}"
        exp_title, exp_display = expected[code]
        assert child["title"] == exp_title, f"{code} title mismatch"
        assert child["code"]["coding"][0]["display"] == exp_display, f"{code} display mismatch"


@pytest.mark.unit
def test_jp_clins_composition_section_code_text_max_zero():
    """Chain #9: JP-CLINS eDS spec pins every section slice `code.text` to
    max=0. clinosim must not emit a `text` field on any section's `code`
    CodeableConcept (parent structuredSection or any child)."""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    parent = comp["section"][0]
    assert "text" not in parent["code"], parent["code"]
    for child in parent["section"]:
        assert "text" not in child["code"], child["code"]


@pytest.mark.unit
def test_jp_clins_composition_extension_version_present():
    """Chain #9: JP-CLINS eDS declares `Composition.extension:version` (min=1)
    on the composition-clinicaldocument-versionNumber URL."""
    from clinosim.modules.output._fhir_composition import (
        _JP_EDS_VERSION_EXTENSION_URL,
        _build_composition,
    )

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    exts = comp.get("extension", [])
    version_ext = [e for e in exts if e.get("url") == _JP_EDS_VERSION_EXTENSION_URL]
    assert len(version_ext) == 1
    assert version_ext[0]["valueString"] == "1"


@pytest.mark.unit
def test_jp_clins_composition_category_discharge():
    """Chain #9: JP-CLINS eDS `Composition.category` min=1 max=1 fixed to
    DISCHARGE under doc-subtypecodes CodeSystem."""
    from clinosim.modules.output._fhir_composition import (
        _JPFHIR_DOC_SUBTYPECODES_SYSTEM,
        _build_composition,
    )

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    category = comp.get("category")
    assert isinstance(category, list) and len(category) == 1
    coding = category[0]["coding"][0]
    assert coding["system"] == _JPFHIR_DOC_SUBTYPECODES_SYSTEM
    assert coding["code"] == "DISCHARGE"


@pytest.mark.unit
def test_jp_clins_composition_all_10_child_sections_have_nonempty_text_div():
    """#286 regression: all 10 JP-CLINS eDS child sections must have non-
    whitespace text.div (FHIR R4 `txt-2`). Session 58 Chain #9 added the 5
    discharge-side slice codes (333/324/344/444/424) but the sections dict
    key names for 444/424 in `_JP_DS_SECTION_CODE` were
    `medication_on_discharge` / `instruction_on_discharge` while the
    narrative pass writes `discharge_medications` / `discharge_instructions`.
    Key drift → empty `<div/>` → 260+ v5 errors.
    """
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    parent = comp["section"][0]
    for child in parent["section"]:
        code = child["code"]["coding"][0]["code"]
        div = (child.get("text") or {}).get("div", "")
        # Strip xhtml wrapper + whitespace
        stripped = (
            div.replace('<div xmlns="http://www.w3.org/1999/xhtml">', "")
            .replace("</div>", "")
            .strip()
        )
        assert stripped, f"child section {code} has empty text.div (txt-2 violation)"


@pytest.mark.unit
def test_jp_clins_composition_meta_lastupdated_from_authored_datetime():
    """Chain #9: `Composition.meta.lastUpdated` min=1 — falls back to authored
    datetime when not builder-set."""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    assert comp["meta"]["lastUpdated"] == "2026-01-20T10:00:00"


@pytest.mark.unit
def test_jp_clins_composition_required_entries_reference_correct_resources():
    """Chain #9 follow-up (#267): 3 of the 4 required `.entry` slices on the
    eDS structuredSection children point at the correct resource types per
    spec. The 4th (hospitalCourseSection.entry → DocumentReference) is
    deferred to a follow-up because clinosim's Composition-format documents
    have no companion DocumentReference resource emitted (`_bb_document_references`
    skips them intentionally). Rather than emit a dangling reference we
    leave the entry off — never-fabricate wins over min=1 on that one slice.
    - detailsOnAdmissionSection.entry → Encounter (min=1 max=1) ✓
    - hospitalCourseSection.entry → DocumentReference (deferred, no entry)
    - detailsOnDischargeSection.entry → Encounter (min=1 max=1) ✓
    - diagnosesOnDischargeSection.entry → Condition (min=1) ✓
    Non-required slices (chief complaint / present illness / etc.) do not
    fabricate an entry when clinosim has no source resource to link.
    """
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    children_by_code = {c["code"]["coding"][0]["code"]: c for c in comp["section"][0]["section"]}

    # 322 = detailsOnAdmission → Encounter
    entries = children_by_code["322"]["entry"]
    assert len(entries) == 1
    assert entries[0]["reference"] == "Encounter/ENC-001"

    # 333 = hospitalCourse — deferred, no entry emitted (see docstring).
    assert "entry" not in children_by_code["333"]

    # 324 = detailsOnDischarge → Encounter
    entries = children_by_code["324"]["entry"]
    assert entries[0]["reference"] == "Encounter/ENC-001"

    # 344 = diagnosesOnDischarge → Condition
    entries = children_by_code["344"]["entry"]
    assert entries[0]["reference"] == "Condition/cond-ENC-001-primary"

    # Non-required section: chief_complaint (352) — no entry emitted.
    assert "entry" not in children_by_code["352"]


@pytest.mark.unit
def test_jp_clins_composition_entry_omitted_when_ids_missing():
    """Never fabricate a broken reference — if encounter_id (or the pieces
    needed to derive a target id) is missing, drop the entry."""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    doc["encounter_id"] = ""
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    children_by_code = {c["code"]["coding"][0]["code"]: c for c in comp["section"][0]["section"]}
    for code in ("322", "324", "344"):
        assert "entry" not in children_by_code[code], code


@pytest.mark.unit
def test_jp_clins_composition_custodian_emitted():
    """Chain #9 follow-up (#267): `Composition.custodian` min=1. Reused from
    the generic composition path — no fabrication if the resource id
    placeholder ever becomes empty."""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    assert comp["custodian"]["reference"].startswith("Organization/")


@pytest.mark.unit
def test_jp_clins_composition_event_period_populated():
    """Chain #9 follow-up (#267): `Composition.event` min=1 max=1 with
    period.start required — falls back to authored_datetime when
    period_start is absent (generic builder emit)."""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    event = comp.get("event")
    assert isinstance(event, list) and len(event) == 1
    period = event[0].get("period", {})
    assert period.get("start")


@pytest.mark.unit
def test_jp_clins_composition_author_has_organization():
    """Chain #9: `Composition.author` min=2 — practitioner + facility organization."""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    authors = comp["author"]
    assert len(authors) >= 2
    refs = [a.get("reference", "") for a in authors]
    assert any(r.startswith("Practitioner/") for r in refs)
    assert any(r.startswith("Organization/") for r in refs)


@pytest.mark.unit
def test_jp_clins_composition_title_is_ja():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    assert comp["title"] == "退院時サマリー"


@pytest.mark.unit
def test_jp_clins_composition_identifier_uri_matches_spec():
    """Session 58 Chain #10: JP-CLINS eDS / eReferral spec
    `Composition.identifier.system` fixedUri =
    `http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier`.
    US / generic path retains the clinosim namespace URI (no spec constraint)."""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    assert comp["identifier"]["system"] == "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"


@pytest.mark.unit
def test_us_composition_identifier_keeps_clinosim_uri():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _us_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "en")
    assert comp["identifier"]["system"] == "urn:clinosim:composition-id"


@pytest.mark.unit
def test_us_discharge_summary_composition_unchanged():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _us_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "en")
    # No JP-CLINS profile
    profs = comp.get("meta", {}).get("profile", [])
    assert not any(p.startswith("http://jpfhir.jp/fhir/eDischargeSummary/") for p in profs), profs
    # Type uses LOINC only, no doc-typecodes leak
    systems = {c.get("system") for c in comp["type"]["coding"]}
    assert "http://loinc.org" in systems
    assert _DOC_TYPE_SYSTEM not in systems
    # Flat 6 sections at top level (no nesting)
    assert len(comp["section"]) == 6
    # No JP section system leaked
    for s in comp["section"]:
        code_coding = s.get("code", {}).get("coding", [])
        for cc in code_coding:
            assert cc.get("system") != _SECTION_SYSTEM
