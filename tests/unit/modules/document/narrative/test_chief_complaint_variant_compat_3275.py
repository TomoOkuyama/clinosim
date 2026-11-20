"""Issue #3275 — JP chief-complaint variants are matched to the visit.

A variant is picked only among those compatible with the patient's age, the
disease's onset type and the encounter type; a variant that is an
examination finding, or that names a mechanism the visit does not have, does
not exist in the pool.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import build_chief_complaint
from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import (
    displayed_chief_complaint as _displayed_chief_complaint,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import (
    load_chief_complaint_variant_rules,
)
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

_GEN = TemplateNarrativeGenerator()


def _ctx(
    disease_id: str,
    *,
    age: int,
    cc_ja: str,
    n: int,
    encounter_type: str = "inpatient",
    protocol: Any = None,
    encounter_protocol: Any = None,
) -> NarrativeContext:
    admitted = datetime(2026, 7, 1, 10, 0)
    patient = PatientProfile(patient_id=f"POP-{n:05d}")
    patient.age = age
    patient.date_of_birth = date(2026 - age - 1, 1, 1)
    enc = SimpleNamespace(
        encounter_id=f"ENC-{n:05d}",
        encounter_type=SimpleNamespace(value=encounter_type),
        admission_datetime=admitted,
        chief_complaint="x",
        chief_complaint_ja=cc_ja,
        severity="moderate",
        discharge_disposition="",
    )
    return NarrativeContext(
        patient=patient,
        encounter=enc,
        encounter_type=enc.encounter_type,
        disease_protocol=protocol if protocol is not None else load_disease_protocol(disease_id),
        encounter_protocol=encounter_protocol,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ADMISSION_HP,
        target_lang="ja",
        locale="jp",
    )


def _pick_all(disease_id: str, age: int, **kw: Any) -> set[str]:
    proto = load_disease_protocol(disease_id)
    cc = proto.chief_complaint["ja"] if isinstance(proto.chief_complaint, dict) else proto.chief_complaint
    return {build_chief_complaint(_GEN, _ctx(disease_id, age=age, cc_ja=cc, n=i, **kw))[0] for i in range(300)}


def test_elderly_variant_never_chosen_for_a_young_patient() -> None:
    seen = _pick_all("urinary_tract_infection", 34)
    assert "高齢者の発熱と全身倦怠感" not in seen
    assert len(seen) > 1


def test_elderly_variant_still_available_for_an_old_patient() -> None:
    assert "高齢者の発熱と全身倦怠感" in _pick_all("urinary_tract_infection", 80)


def test_hip_fracture_never_uses_an_examination_finding() -> None:
    for age in (40, 84):
        assert not any("外旋位" in s for s in _pick_all("hip_fracture", age))


def test_onset_tagged_variant_follows_the_disease_onset_type() -> None:
    # bacterial_pneumonia onset_type is subacute: "3日前より..." fits,
    # acute-only phrasing never does.
    rules = load_chief_complaint_variant_rules()["asthma_exacerbation"]
    acute_only = [r.text for r in rules if r.onset_types == ["acute"]]
    assert acute_only, "asthma_exacerbation must carry an acute-tagged variant"
    proto = load_disease_protocol("bacterial_pneumonia")
    for r in load_chief_complaint_variant_rules()["bacterial_pneumonia"]:
        if r.onset_types:
            assert "subacute" in r.onset_types, r.text
    assert proto is not None


def test_encounter_type_tag_excludes_inpatient_only_variant_in_ed() -> None:
    rules = load_chief_complaint_variant_rules()["depression_inpatient"]
    tagged = [r for r in rules if r.encounter_types]
    assert tagged
    proto = load_disease_protocol("depression_inpatient")
    cc = proto.chief_complaint["ja"]
    seen = {
        build_chief_complaint(_GEN, _ctx("depression_inpatient", age=40, cc_ja=cc, n=i, encounter_type="emergency"))[0]
        for i in range(200)
    }
    assert not seen & {r.text for r in tagged}


def test_ankle_sprain_for_an_old_faller_is_never_sports() -> None:
    from clinosim.modules.encounter.protocol import load_encounter_condition

    ep = load_encounter_condition("ankle_sprain")
    cc = ep["chief_complaint"]["ja"]
    seen = set()
    for i in range(300):
        ctx = _ctx(
            "heart_failure_exacerbation",
            age=84,
            cc_ja=cc,
            n=i,
            encounter_type="emergency",
            protocol=None,
            encounter_protocol=ep,
        )
        ctx.disease_protocol = None
        seen.add(build_chief_complaint(_GEN, ctx)[0])
    assert len(seen) > 1
    assert not any("スポーツ" in s for s in seen)


def test_hpi_complaint_and_section_complaint_are_the_same() -> None:
    proto = load_disease_protocol("urinary_tract_infection")
    cc = proto.chief_complaint["ja"]
    for i in range(60):
        ctx = _ctx("urinary_tract_infection", age=34, cc_ja=cc, n=i)
        assert build_chief_complaint(_GEN, ctx)[0] == _displayed_chief_complaint(cc, ctx)


# Wording that describes what the examiner sees or measures, or a diagnosis,
# not what the patient reports. Pool heads (the disease protocol's own
# chief complaint) are authored elsewhere and not linted here.
_EXAM_FINDING_MARKERS = (
    "外旋位",
    "短縮",
    "徴候",
    "羽ばたき振戦",
    "腸雑音",
    "補助呼吸筋",
    "SpO2",
    "皮下気腫",
    "フォーク状",
    "ORIF",
    "凝固能",
)


def test_no_non_head_variant_is_an_examination_finding() -> None:
    bad = [
        (key, r.text)
        for key, rules in load_chief_complaint_variant_rules().items()
        for r in rules[1:]
        if any(m in r.text for m in _EXAM_FINDING_MARKERS)
    ]
    assert not bad, bad


def test_no_sports_variant_without_a_sports_complaint() -> None:
    bad = [
        (key, r.text)
        for key, rules in load_chief_complaint_variant_rules().items()
        for r in rules
        if "スポーツ" in r.text
    ]
    assert not bad, bad


@pytest.mark.parametrize("key", sorted(load_chief_complaint_variant_rules()))
def test_head_variant_is_unconditional(key: str) -> None:
    head = load_chief_complaint_variant_rules()[key][0]
    assert head.min_age is None and head.max_age is None
    assert not head.onset_types and not head.encounter_types


def _texts() -> dict[str, list[str]]:
    from clinosim.modules.document.reference_data_loaders import load_chief_complaint_variant_rules as _rules

    return {k: [v.text for v in pool] for k, pool in _rules().items()}
