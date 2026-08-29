"""P2-13 PR2b:JP-CLINS 診療情報提供書 Composition unit tests(JP-only)."""

from __future__ import annotations

import pytest

_PROFILE_URL = "http://jpfhir.jp/fhir/eReferral/StructureDefinition/JP_Composition_eReferral"
_DOC_TYPE_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/document-section"


def _jp_referral_doc():
    return {
        "document_id": "doc-ENC-001-02",
        "document_type": "REFERRAL_NOTE",
        "loinc_code": "57133-1",
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
                "referring_institution": "紹介元:当院(急性期一般病棟)。",
                "referral_destination": "紹介先:他院。継続加療目的。",
                "referral_purpose": "紹介目的:継続加療のため。",
                "diagnoses_and_complaint": "【傷病名】\n1. 細菌性肺炎（J13）\n\n【主訴】\n発熱・咳嗽",
                "present_illness_ref": "3日前より発熱と咳嗽を認め、当院受診となった。",
            }
        },
    }


@pytest.mark.unit
def test_jp_clins_referral_composition_type():
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    systems = {c.get("system") for c in comp["type"]["coding"]}
    # Session 57 v3 fix: eReferral profile constrains type.coding to max=1,
    # so only the doc-typecodes coding is emitted (LOINC dropped).
    assert _DOC_TYPE_SYSTEM in systems
    assert "http://loinc.org" not in systems
    assert len(comp["type"]["coding"]) == 1
    assert comp["title"] == "診療情報提供書"


@pytest.mark.unit
def test_jp_clins_referral_composition_profile():
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    profs = comp.get("meta", {}).get("profile", [])
    assert _PROFILE_URL in profs


@pytest.mark.unit
def test_jp_clins_referral_composition_top_level_sections():
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    top = comp["section"]
    top_codes = [s["code"]["coding"][0]["code"] for s in top]
    assert top_codes == ["920", "910", "300"], top_codes
    for s in top:
        assert s["code"]["coding"][0]["system"] == _SECTION_SYSTEM


@pytest.mark.unit
def test_jp_clins_referral_composition_structural_children():
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    structural = [s for s in comp["section"] if s["code"]["coding"][0]["code"] == "300"][0]
    child_codes = [c["code"]["coding"][0]["code"] for c in structural["section"]]
    assert child_codes == ["950", "340", "360"], child_codes


@pytest.mark.unit
def test_jp_clins_referral_composition_section_content():
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition
    from clinosim.modules.output.fhir_r4.documents.referral_orgs import (
        pick_external_hospital,
    )

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    top_by_code = {s["code"]["coding"][0]["code"]: s for s in comp["section"]}
    # 920 紹介元 — 当院 pin unchanged (outgoing referral)
    assert "当院" in top_by_code["920"]["text"]["div"]
    # Issue #924: 910 紹介先 no longer says `他院`; it names the sampled
    # external hospital from the JP external-organization catalog. The
    # sampled entry is deterministic on (patient_id, encounter_id).
    ext = pick_external_hospital(doc["patient_id"], doc["encounter_id"], country="JP")
    assert ext is not None
    assert ext["name"] in top_by_code["910"]["text"]["div"]
    assert "他院" not in top_by_code["910"]["text"]["div"]
    # 300 structural nested
    structural_by_code = {c["code"]["coding"][0]["code"]: c for c in top_by_code["300"]["section"]}
    assert "継続加療" in structural_by_code["950"]["text"]["div"]
    assert "細菌性肺炎" in structural_by_code["340"]["text"]["div"]
    assert "3日前" in structural_by_code["360"]["text"]["div"]


@pytest.mark.unit
def test_jp_clins_referral_composition_chain9_pattern_top_level():
    """#289 (sibling of eDS Chain #9): JP-CLINS eReferral の 5 top-level
    制約を pin — Composition.extension:version + category + author≥2 +
    meta.lastUpdated + event.code。sec 58 で eDS には適用済だが eReferral
    に sibling drift、v5 で 120 件 error。
    """
    from clinosim.modules.output.fhir_r4.documents.composition import (
        _JP_EDS_VERSION_EXTENSION_URL,
        _JP_ER_CATEGORY_CODE,
        _JP_ER_CATEGORY_DISPLAY_JA,
        _JP_ER_EVENT_CODE_TEXT_JA,
        _JPFHIR_DOC_SUBTYPECODES_SYSTEM,
        _build_composition,
    )

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")

    # 1. extension:version
    exts = comp.get("extension", [])
    version_ext = [e for e in exts if e.get("url") == _JP_EDS_VERSION_EXTENSION_URL]
    assert len(version_ext) == 1
    assert version_ext[0]["valueString"] == "1"

    # 2. category (min=1 max=1, doc-subtypecodes CS, CONSULT / 他科コンサルト)
    category = comp.get("category")
    assert isinstance(category, list) and len(category) == 1
    coding = category[0]["coding"][0]
    assert coding["system"] == _JPFHIR_DOC_SUBTYPECODES_SYSTEM
    assert coding["code"] == _JP_ER_CATEGORY_CODE == "CONSULT"
    # doc-subtypecodes CS authoritative display for CONSULT
    assert coding["display"] == _JP_ER_CATEGORY_DISPLAY_JA == "他科コンサルト"

    # 3. author min=2 — Practitioner + Organization
    # #330 session 61: eReferral profile author targetProfile は
    # JP_Organization_eCS 準拠を要求。Issue #746 で hospital-main 自身が
    # 両 profile を宣言するよう unify したため、参照先は hospital-main。
    authors = comp.get("author", [])
    assert len(authors) >= 2
    refs = [str(a.get("reference", "")) for a in authors]
    assert any(r.startswith("Practitioner/") for r in refs)
    assert "Organization/hospital-main" in refs
    assert "Organization/hospital-main-ecs" not in refs

    # #330: Composition.custodian も同 spec で eCS 準拠必須。unify 済
    # hospital-main を参照。
    assert comp.get("custodian", {}).get("reference") == "Organization/hospital-main"

    # 4. meta.lastUpdated
    assert comp["meta"]["lastUpdated"] == "2026-01-20T10:00:00"

    # 5. event.code min=1 (text-only satisfies)
    # #309 session 60:code は Array 必須(FHIR JSON base cardinality 0..*)
    # + text は spec fixedString "診療情報提供書発行"。
    events = comp.get("event", [])
    assert events
    code = events[0].get("code")
    assert isinstance(code, list) and len(code) == 1
    assert code[0].get("text") == _JP_ER_EVENT_CODE_TEXT_JA == "診療情報提供書発行"
    # coding は spec max=0(text-only)。
    assert "coding" not in code[0]


@pytest.mark.unit
def test_jp_clins_referral_composition_from_to_section_entries():
    """#296 / Issue #924:JP-CLINS eReferral は 920(紹介元 = referralFrom
    Organization)と 910(紹介先 = referralToOrganization)の 2 section
    slice それぞれに entry: Reference(Organization) min=1 を要求。

    920 紹介元 は当院 (outgoing referral) — `Organization/hospital-main`
    に pin。#313 の slice discriminator は eCS profile 準拠 (Issue #746
    で hospital-main 自身が JP_Organization + JP_Organization_eCS を両
    宣言) で満たされる。

    Issue #924 fix: 910 紹介先 は
    ``clinosim/locale/jp/external_organizations.yaml`` catalog から
    (patient_id, encounter_id) sha256 modulo で決定的に sample した
    外部 Organization を参照。fix 以前は 920 と同じ hospital-main を
    pin して 100 % self-loop を作っていた (bug reproducible in the
    p=1000 audit)。
    """
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition
    from clinosim.modules.output.fhir_r4.documents.referral_orgs import (
        pick_external_hospital,
    )

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    top_by_code = {s["code"]["coding"][0]["code"]: s for s in comp["section"]}
    assert top_by_code["920"].get("entry") == [{"reference": "Organization/hospital-main"}]
    ext = pick_external_hospital(doc["patient_id"], doc["encounter_id"], country="JP")
    assert ext is not None
    assert top_by_code["910"].get("entry") == [{"reference": f"Organization/{ext['id']}"}]
    # Anti-regression on the Issue #924 self-loop.
    assert top_by_code["920"]["entry"] != top_by_code["910"]["entry"]


@pytest.mark.unit
def test_referral_note_fires_deterministic():
    """20% fire rate は (encounter_id, patient_id) ごとに決定的であること。"""
    from clinosim.modules.document.engine import _referral_note_fires

    # Same inputs → same output
    assert _referral_note_fires("ENC-1", "P1") == _referral_note_fires("ENC-1", "P1")
    # Different encounter_id → possibly different (but deterministic)
    # This just documents that _fires is deterministic (not a probability test)
    outcomes = {_referral_note_fires(f"ENC-{i}", "P1") for i in range(1000)}
    assert outcomes == {True, False}, "fires should hit both branches over 1000 samples"


@pytest.mark.unit
def test_referral_external_org_sampling_is_deterministic_and_stable():
    """Issue #924: pick_external_hospital must be deterministic across
    calls and yield distinct catalog rows for distinct
    (patient_id, encounter_id) pairs — no master-RNG consumption, no
    call-order sensitivity.
    """
    from clinosim.modules.output.fhir_r4.documents.referral_orgs import (
        pick_external_hospital,
    )

    # Determinism
    a1 = pick_external_hospital("POP-000001", "ENC-001", country="JP")
    a2 = pick_external_hospital("POP-000001", "ENC-001", country="JP")
    assert a1 is not None and a1["id"] == a2["id"]

    # Coverage: over a synthetic cohort we hit >1 distinct hospital.
    picks = {pick_external_hospital(f"POP-{i:06d}", f"ENC-{i:04d}", country="JP")["id"] for i in range(200)}
    assert len(picks) > 1


@pytest.mark.unit
def test_bb_compositions_emits_referenced_external_organizations():
    """Issue #924: `_bb_compositions` must emit an Organization resource
    for every external hospital referenced by any 57133-1 referral
    Composition (deduplicated), and the reference in the Composition's
    910 section must resolve to that Organization by id. No self-loop
    (紹介元 != 紹介先).
    """
    from types import SimpleNamespace

    from clinosim.modules.output.fhir_r4.documents.composition import _bb_compositions

    doc = _jp_referral_doc()
    ctx = SimpleNamespace(
        record={"documents": [doc], "encounters": [], "extensions": {}},
        country="JP",
        patient_id=doc["patient_id"],
        primary_enc_id=doc["encounter_id"],
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        patient_sex="",
    )
    resources = _bb_compositions(ctx)
    orgs = [r for r in resources if r.get("resourceType") == "Organization"]
    comps = [r for r in resources if r.get("resourceType") == "Composition"]
    assert len(comps) == 1
    assert len(orgs) >= 1
    ext_ids = {o["id"] for o in orgs}
    assert all(oid.startswith("ext-hosp-") for oid in ext_ids)

    comp = comps[0]
    top_by_code = {s["code"]["coding"][0]["code"]: s for s in comp["section"]}
    from_entry = top_by_code["920"]["entry"][0]["reference"]
    to_entry = top_by_code["910"]["entry"][0]["reference"]
    assert from_entry == "Organization/hospital-main"
    assert to_entry.startswith("Organization/ext-hosp-")
    # No self-loop.
    assert from_entry != to_entry
    # And the referenced external org appears in the emit output.
    assert to_entry.split("/", 1)[1] in ext_ids


@pytest.mark.unit
def test_referral_note_fire_rate_approximately_20pct():
    """N=2000 で実測発火率が 20% ±5% 以内であること。"""
    from clinosim.modules.document.engine import _referral_note_fires

    fires = sum(1 for i in range(2000) if _referral_note_fires(f"ENC-{i:04d}", f"P-{i:04d}"))
    rate = fires / 2000
    assert 0.15 <= rate <= 0.25, f"referral fire rate {rate} outside [0.15, 0.25]"
