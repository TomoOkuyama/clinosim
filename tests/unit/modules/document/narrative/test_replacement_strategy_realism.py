"""Session 104 Tier 1 realism tests for ``replacement_strategy``.

Split out of ``test_replacement_strategy.py`` (originally 1647 LOC) so
the patient_demographics / patient_biometrics / health_literacy_tag
emission tests live together.
"""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.document.narrative.replacement_strategy import (
    _build_extra_context,
    _health_literacy_tag,
    _render_patient_biometrics,
    _render_patient_demographics,
)
from clinosim.types.document import (
    DocumentType,
    DocumentTypeSpec,
    FormatType,
    NarrativeContext,
)


def _make_spec(
    stage2_strategy: str = "template_only",
    llm_enabled_sections: tuple[str, ...] = (),
    format_type: FormatType = FormatType.COMPOSITION,
) -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="admission_hp",
        loinc_code="34117-2",
        format_type=format_type,
        countries_supported=("jp", "us"),
        generation_frequency="admission_once",
        composition_sections=("hpi", "assessment_and_plan"),
        stage2_strategy=stage2_strategy,
        llm_enabled_sections=llm_enabled_sections,
    )


def _bundle_spec(
    llm_enabled_sections: tuple[str, ...] = ("subjective", "assessment", "plan"),
    format_type: FormatType = FormatType.COMPOSITION,
    type_key: str = "outpatient_soap",
    composition_sections: tuple[str, ...] = ("subjective", "objective", "assessment", "plan"),
) -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key=type_key,
        loinc_code="34131-3",
        format_type=format_type,
        countries_supported=("jp", "us"),
        generation_frequency="encounter_once",
        composition_sections=composition_sections,
        stage2_strategy="template_seed_bundle",
        llm_enabled_sections=llm_enabled_sections,
    )


def _make_ctx() -> NarrativeContext:
    patient = SimpleNamespace(age=55, sex="M", chronic_conditions=[])
    encounter = SimpleNamespace(encounter_id="enc-test")
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
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


# ─────────────────────────────────────────────────────────────────
# Session 104 Tier 1: patient_demographics + patient_biometrics +
# health_literacy_tag realism keys
# ─────────────────────────────────────────────────────────────────


def _rich_patient() -> SimpleNamespace:
    return SimpleNamespace(
        age=72,
        sex="female",
        chronic_conditions=[],
        employment_status="retired",
        occupation="",
        smoking_status="former_smoker",
        alcohol_use="occasional",
        marital_status="widowed",
        insurance_type="late_elderly",
        height_cm=158,
        weight_kg=52.4,
        bmi=21.0,
        blood_type="O",
        rh_factor="positive",
        health_literacy=0.35,
    )


def _empty_patient() -> SimpleNamespace:
    return SimpleNamespace(
        age=None,
        sex="",
        chronic_conditions=[],
        employment_status="",
        occupation="",
        smoking_status="",
        alcohol_use="",
        marital_status="",
        insurance_type="",
        height_cm=None,
        weight_kg=None,
        bmi=0,
        blood_type="",
        rh_factor="",
        health_literacy=None,
    )


def test_render_patient_demographics_ja_full_anchor() -> None:
    out = _render_patient_demographics(_rich_patient(), lang="ja")
    assert "72歳女性" in out
    assert "退職" in out
    assert "元喫煙" in out
    assert "機会飲酒" in out
    assert "死別" in out
    assert "後期高齢者医療制度" in out


def test_render_patient_demographics_en_full_anchor() -> None:
    out = _render_patient_demographics(_rich_patient(), lang="en")
    assert "72 y/o female" in out
    assert "retired" in out
    assert "former smoker" in out
    assert "occasional drinker" in out  # shared vocabulary (Issue #2269)
    assert "widowed" in out
    assert "Late-Elderly Medical Care System" in out


def test_render_patient_demographics_silent_on_empty_patient() -> None:
    assert _render_patient_demographics(_empty_patient(), lang="ja") == ""
    assert _render_patient_demographics(_empty_patient(), lang="en") == ""


def test_render_patient_demographics_localizes_occupation_ja() -> None:
    """Phase 1c-1 (2026-09-22): pre-fix, the demographics renderer emitted
    the raw ``occupation`` string ("service") verbatim into JA output —
    the JP p=500 H100 audit surfaced 「32歳男性、service、非喫煙、s、
    dependent」 as the ed_note::hpi opening line. Occupation now routes
    through ``_OCCUPATION_LABELS`` so common vocabulary values (service,
    office, healthcare, manufacturing, ...) resolve to JA labels."""
    p = SimpleNamespace(
        age=32,
        sex="male",
        employment_status="employed",
        occupation="service",
        smoking_status="never",
        alcohol_use="none",
        marital_status="single",
        insurance_type="employee_dependent",
    )
    ja = _render_patient_demographics(p, lang="ja")
    assert "サービス業" in ja
    assert "service" not in ja  # raw enum must not leak
    en = _render_patient_demographics(p, lang="en")
    assert "service industry" in en


def test_render_patient_demographics_localizes_marital_short_codes() -> None:
    """Phase 1c-1: PatientProfile.marital_status is emitted as a
    single-letter uppercase code (M / S / D / W / P) by the demographics
    populator. Pre-fix, ``_localize_token`` lower-cased them to
    "m"/"s"/... which had no table entry and fell back to the raw slug
    ("s") — 600 patients / 2 cohorts leaked verbatim. Alias entries now
    map each short code to the full form's JA/EN labels."""
    for code, ja_expected, en_expected in [
        ("M", "既婚", "married"),
        ("S", "独身", "single"),
        ("D", "離婚", "divorced"),
        ("W", "死別", "widowed"),
        ("P", "内縁", "partnered"),
    ]:
        p = SimpleNamespace(
            age=45,
            sex="female",
            employment_status="",
            occupation="",
            smoking_status="",
            alcohol_use="",
            marital_status=code,
            insurance_type="",
        )
        ja = _render_patient_demographics(p, lang="ja")
        assert ja_expected in ja, f"code={code!r} missing {ja_expected!r} in {ja!r}"
        assert code.lower() not in ja  # bare single letter must not leak
        en = _render_patient_demographics(p, lang="en")
        assert en_expected in en


def test_render_patient_demographics_localizes_jp_insurance_short_forms() -> None:
    """Phase 1c-1: the JP identity module writes short-form
    insurance_type values (`dependent` / `national` / `employee`) rather
    than the canonical `employee_dependent` / `national_health_insurance`
    slugs the pre-fix table indexed by. 200/600 JP patients carried
    "dependent" verbatim into the LLM prompt pre-fix — now covered."""
    for raw, ja_expected in [
        ("dependent", "被用者保険 (被扶養者)"),
        ("employee", "被用者保険 (被保険者)"),
        ("national", "国民健康保険"),
        ("late_elderly", "後期高齢者医療制度"),
        ("NHI_employee", "国民健康保険 (被用者相当)"),
    ]:
        p = SimpleNamespace(
            age=70,
            sex="male",
            employment_status="",
            occupation="",
            smoking_status="",
            alcohol_use="",
            marital_status="",
            insurance_type=raw,
        )
        ja = _render_patient_demographics(p, lang="ja")
        assert ja_expected in ja, f"raw={raw!r} missing {ja_expected!r} in {ja!r}"
        assert raw.lower() not in ja  # raw enum must not leak


def test_render_patient_demographics_localizes_social_alcohol_ja() -> None:
    """Phase 1c-1: ``alcohol_use="social"`` was missing from
    ``_ALCOHOL_LABELS`` (which only had "occasional"), so 157/600 JP
    patients emitted the raw English "social" inside JA demographics."""
    p = SimpleNamespace(
        age=50,
        sex="male",
        employment_status="",
        occupation="",
        smoking_status="never",
        alcohol_use="social",
        marital_status="",
        insurance_type="",
    )
    ja = _render_patient_demographics(p, lang="ja")
    assert "機会飲酒" in ja
    assert "social" not in ja


def test_render_patient_demographics_partial_skips_missing() -> None:
    p = SimpleNamespace(
        age=68,
        sex="male",
        employment_status="",
        occupation="",
        smoking_status="never",
        alcohol_use="",
        marital_status="",
        insurance_type="",
    )
    ja = _render_patient_demographics(p, lang="ja")
    en = _render_patient_demographics(p, lang="en")
    # Age + sex + one social item, nothing fabricated for missing fields
    assert ja == "68歳男性、非喫煙者"  # shared vocabulary (Issue #2269)
    assert en == "68 y/o male, non-smoker"


def test_render_patient_biometrics_full_line() -> None:
    ja = _render_patient_biometrics(_rich_patient(), lang="ja")
    en = _render_patient_biometrics(_rich_patient(), lang="en")
    assert "身長 158 cm" in ja
    assert "体重 52.4 kg" in ja
    assert "BMI 21.0" in ja
    assert "血液型 O+" in ja
    assert "Ht 158 cm" in en
    assert "Wt 52.4 kg" in en
    assert "blood type O+" in en


def test_render_patient_biometrics_silent_on_missing() -> None:
    assert _render_patient_biometrics(_empty_patient(), lang="ja") == ""
    assert _render_patient_biometrics(_empty_patient(), lang="en") == ""


def test_render_patient_biometrics_rh_negative() -> None:
    p = SimpleNamespace(
        height_cm=170,
        weight_kg=68,
        bmi=23.5,
        blood_type="AB",
        rh_factor="negative",
    )
    assert "AB-" in _render_patient_biometrics(p, lang="en")


def test_health_literacy_tag_bands() -> None:
    # Fixed thresholds: <0.4 low, 0.4-<0.7 medium, ≥0.7 high
    def _tag(v):
        return _health_literacy_tag(SimpleNamespace(health_literacy=v))

    assert _tag(0.0) == "low"
    assert _tag(0.39) == "low"
    assert _tag(0.4) == "medium"
    assert _tag(0.69) == "medium"
    assert _tag(0.7) == "high"
    assert _tag(1.0) == "high"
    # Missing → silent
    assert _tag(None) == ""
    assert _health_literacy_tag(SimpleNamespace(health_literacy=None)) == ""


def test_health_literacy_tag_absent_field_silent() -> None:
    # A patient object with no health_literacy attribute at all
    p = SimpleNamespace()
    assert _health_literacy_tag(p) == ""


def _make_ctx_with_patient(patient, doc_type="progress_note", lang="ja") -> NarrativeContext:
    dt = getattr(DocumentType, doc_type.upper())
    return NarrativeContext(
        patient=patient,
        encounter=SimpleNamespace(encounter_id="enc"),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=1,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=dt,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def test_build_extra_context_emits_patient_demographics_when_template_lacks_social_history() -> None:
    ctx = _make_ctx_with_patient(_rich_patient(), doc_type="progress_note", lang="ja")
    spec = _bundle_spec(type_key="progress_note")
    extra = _build_extra_context(ctx, spec, template_section_names=set())
    assert "patient_demographics" in extra
    assert "72歳女性" in extra["patient_demographics"]


def test_build_extra_context_skips_patient_demographics_when_template_has_social_history() -> None:
    ctx = _make_ctx_with_patient(_rich_patient(), doc_type="admission_hp", lang="ja")
    spec = _bundle_spec(type_key="admission_hp", llm_enabled_sections=("hpi", "assessment_and_plan"))
    extra = _build_extra_context(ctx, spec, template_section_names={"social_history"})
    assert "patient_demographics" not in extra  # skipped because template renders it


def test_build_extra_context_emits_patient_biometrics_only_for_scoped_doc_types() -> None:
    # operative_note is in _BIOMETRICS_DOC_TYPES → emit
    ctx = _make_ctx_with_patient(_rich_patient(), doc_type="operative_note", lang="en")
    spec = _bundle_spec(type_key="operative_note", llm_enabled_sections=("op_findings",))
    extra_op = _build_extra_context(ctx, spec, template_section_names=set())
    assert "patient_biometrics" in extra_op
    assert "BMI 21.0" in extra_op["patient_biometrics"]

    # progress_note is NOT in the biometrics set → skip
    ctx_pn = _make_ctx_with_patient(_rich_patient(), doc_type="progress_note", lang="en")
    spec_pn = _bundle_spec(type_key="progress_note")
    extra_pn = _build_extra_context(ctx_pn, spec_pn, template_section_names=set())
    assert "patient_biometrics" not in extra_pn


def test_build_extra_context_emits_health_literacy_tag_for_patient_facing_docs() -> None:
    # discharge_summary is patient-facing → tag emitted
    ctx = _make_ctx_with_patient(_rich_patient(), doc_type="discharge_summary", lang="ja")
    spec = _bundle_spec(type_key="discharge_summary", llm_enabled_sections=("discharge_instructions",))
    extra = _build_extra_context(ctx, spec, template_section_names=set())
    assert extra.get("health_literacy_tag") == "low"

    # progress_note is physician-to-physician → tag skipped (invariant tone)
    ctx_pn = _make_ctx_with_patient(_rich_patient(), doc_type="progress_note", lang="ja")
    spec_pn = _bundle_spec(type_key="progress_note")
    extra_pn = _build_extra_context(ctx_pn, spec_pn, template_section_names=set())
    assert "health_literacy_tag" not in extra_pn


def test_build_extra_context_universal_keys_silent_on_empty_patient() -> None:
    ctx = _make_ctx_with_patient(_empty_patient(), doc_type="discharge_summary", lang="ja")
    spec = _bundle_spec(type_key="discharge_summary", llm_enabled_sections=("discharge_instructions",))
    extra = _build_extra_context(ctx, spec, template_section_names=set())
    assert "patient_demographics" not in extra
    assert "patient_biometrics" not in extra
    assert "health_literacy_tag" not in extra
