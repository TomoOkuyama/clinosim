"""Composition sections (ADMISSION_HP / DISCHARGE_SUMMARY / nursing /
ED / care-plan / op / procedure / etc.) narrative renderer.

Extracted verbatim from
``template_generator.TemplateNarrativeGenerator._render_composition_sections``
as step C1c of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical — the class method is now a thin delegator.

This renderer dispatches to ~85 ``_build_<section>`` methods on the
generator instance. Following the C1b pattern, it accepts ``generator``
as its first argument and delegates each section-builder lookup back
to it. Later refactors can lift individual section builders out as
free-standing helpers one at a time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.types.document import NarrativeContext, NarrativeOutput

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


def render_composition_sections(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext, spec: DocumentTypeSpec
) -> NarrativeOutput:
    """Build section dict per spec.composition_sections."""
    facts: list[str] = []
    sections: dict[str, str] = {}

    section_builders = {
        # Stage 1 sections
        "chief_complaint": generator._build_chief_complaint,
        "hpi": generator._build_hpi,
        "past_medical_history": generator._build_past_medical_history,
        "medications_at_home": generator._build_medications_at_home,
        "allergies": generator._build_allergies,
        "social_history": generator._build_social_history,
        "family_history": generator._build_family_history,
        "physical_examination": generator._build_physical_examination,
        "assessment_and_plan": generator._build_assessment_and_plan,
        "admission_summary": generator._build_admission_summary,
        "hospital_course": generator._build_hospital_course,
        "discharge_diagnoses": generator._build_discharge_diagnoses,
        "discharge_medications": generator._build_discharge_medications,
        "discharge_instructions": generator._build_discharge_instructions,
        "follow_up": generator._build_follow_up,
        # ADMISSION_NURSING_ASSESSMENT sections
        "nursing_history": generator._build_nursing_history,
        "adl_assessment": generator._build_adl_assessment,
        "risk_assessments": generator._build_risk_assessments,
        "nursing_diagnosis": generator._build_nursing_diagnosis,
        "care_plan": generator._build_care_plan,
        # NURSING_DISCHARGE_SUMMARY sections
        "admission_status": generator._build_nursing_admission_status,
        "nursing_interventions_provided": generator._build_nursing_interventions_provided,
        "patient_education": generator._build_patient_education,
        "discharge_readiness": generator._build_discharge_readiness,
        # OUTPATIENT_SOAP sections (reads encounter_protocol.narrative)
        "subjective": generator._build_outpatient_subjective,
        "objective": generator._build_outpatient_objective,
        "assessment": generator._build_outpatient_assessment,
        "plan": generator._build_outpatient_plan,
        # ED_NOTE sections
        "triage_details": generator._build_triage_details,
        "physical_exam": generator._build_ed_physical_exam,
        "ed_workup": generator._build_ed_workup,
        "disposition": generator._build_ed_disposition,
        # ADMISSION_CARE_PLAN sections (LOINC 18776-5)
        "ward_and_room": generator._build_acp_ward_and_room,
        "other_staff": generator._build_acp_other_staff,
        "diagnosis": generator._build_acp_diagnosis,
        "symptoms": generator._build_acp_symptoms,
        "treatment_plan": generator._build_acp_treatment_plan,
        "test_schedule": generator._build_acp_test_schedule,
        "surgery_schedule": generator._build_acp_surgery_schedule,
        "estimated_los": generator._build_acp_estimated_los,
        "special_nutrition_management": generator._build_acp_special_nutrition_management,
        "other_plans": generator._build_acp_other_plans,
        # NUTRITION_CARE_PLAN sections (LOINC 80791-7)
        "ward_and_physician": generator._build_ncp_ward_and_physician,
        "dietitian": generator._build_ncp_dietitian,
        "nutrition_risk": generator._build_ncp_nutrition_risk,
        "nutrition_assessment": generator._build_ncp_nutrition_assessment,
        "nutrition_goals": generator._build_ncp_nutrition_goals,
        "nutrition_supply": generator._build_ncp_nutrition_supply,
        "dysphagia_diet": generator._build_ncp_dysphagia_diet,
        "dietary_content": generator._build_ncp_dietary_content,
        "nutrition_counseling": generator._build_ncp_nutrition_counseling,
        "other_issues": generator._build_ncp_other_issues,
        "reassessment_timing": generator._build_ncp_reassessment_timing,
        "discharge_evaluation": generator._build_ncp_discharge_evaluation,
        # P2-13 PR2a: JP-CLINS discharge summary sections (JP only)
        "admission_reason": generator._build_admission_reason,
        "admission_details": generator._build_admission_details,
        "admission_diagnoses": generator._build_admission_diagnoses,
        "present_illness": generator._build_present_illness,
        # JP-CLINS eDS discharge-side section builder. The other 4
        # discharge-side keys (hospital_course / discharge_diagnoses /
        # discharge_medications / discharge_instructions) reuse the
        # shared stage 1 entries above.
        "discharge_details": generator._build_discharge_details,
        # P2-13 PR2b: JP-CLINS referral sections (JP only)
        "referring_institution": generator._build_referring_institution,
        "referral_destination": generator._build_referral_destination,
        "referral_purpose": generator._build_referral_purpose,
        "diagnoses_and_complaint": generator._build_diagnoses_and_complaint,
        "present_illness_ref": generator._build_present_illness_ref,
        # P2-13 PR3: JP-eCheckup checkup report sections (JP only, opt-in)
        "checkup_lab_results": generator._build_checkup_lab_results,
        "checkup_questionnaire": generator._build_checkup_questionnaire,
        # REHABILITATION_PLAN sections (LOINC 34823-5)
        "patient_and_diagnosis": generator._build_rp_patient_and_diagnosis,
        "rehab_team": generator._build_rp_rehab_team,
        "functional_status": generator._build_rp_functional_status,
        "basic_movement": generator._build_rp_basic_movement,
        "session_frequency": generator._build_rp_session_frequency,
        "goals": generator._build_rp_goals,
        "policy": generator._build_rp_policy,
        "discharge_estimate": generator._build_rp_discharge_estimate,
        "explanation_consent": generator._build_rp_explanation_consent,
        # Issue #961: DEATH_CERTIFICATE sections (LOINC 64297-5).
        "immediate_cause_of_death": generator._build_dc_immediate_cause,
        "duration_of_immediate_cause": generator._build_dc_duration_of_immediate_cause,
        "underlying_cause_of_death": generator._build_dc_underlying_cause,
        "contributing_conditions": generator._build_dc_contributing_conditions,
        "manner_of_death": generator._build_dc_manner_of_death,
        "autopsy_status": generator._build_dc_autopsy_status,
        # Issue #961 extension: DEATH_DISCHARGE_SUMMARY sections
        # (LOINC 18842-5 with title 死亡退院サマリー). Every section
        # produces a clinically-defensible template narrative from
        # CIF facts (admission dates, LOS, diagnoses, complications,
        # working diagnoses, autopsy sample) — LLM refinement is
        # opt-in polish, not a requirement for narrative validity.
        "admission_state": generator._build_dds_admission_state,
        "treatment_course": generator._build_dds_treatment_course,
        "terminal_course": generator._build_dds_terminal_course,
        "circumstances_of_death": generator._build_dds_circumstances_of_death,
        "cause_of_death": generator._build_dds_cause_of_death,
        "complications_and_comorbidities": generator._build_dds_complications_and_comorbidities,
        "family_communication": generator._build_dds_family_communication,
        "autopsy_status_and_findings": generator._build_dds_autopsy_status_and_findings,
        # Issue #991: OPERATIVE_NOTE sections (LOINC 11504-8). Each
        # builder scopes to the encounter's primary surgical procedure
        # via `_primary_surgical_procedure`; missing data degrades to
        # a fallback string rather than fabrication.
        "op_procedure_name": generator._build_op_procedure_name,
        "op_anesthesia": generator._build_op_anesthesia,
        "op_surgeon": generator._build_op_surgeon,
        "op_findings": generator._build_op_findings,
        "op_course": generator._build_op_course,
        "op_specimens": generator._build_op_specimens,
        "op_blood_loss": generator._build_op_blood_loss,
        "op_equipment": generator._build_op_equipment,
        "op_postop_plan": generator._build_op_postop_plan,
        # Issue #992: PROCEDURE_NOTE sections (LOINC 28570-0). Keys
        # are ``pn_``-prefixed so they never collide with the
        # generic ``course`` / ``complications`` / ``specimens``
        # slugs a future document type may reuse.
        "pn_procedure_name": generator._build_pn_procedure_name,
        "pn_consent": generator._build_pn_consent,
        "pn_performer": generator._build_pn_performer,
        "pn_analgesia": generator._build_pn_analgesia,
        "pn_course": generator._build_pn_course,
        "pn_complications": generator._build_pn_complications,
        "pn_specimens": generator._build_pn_specimens,
        "pn_postop_plan": generator._build_pn_postop_plan,
    }

    # P2-13 PR2a: use the JP-specific section list when country=JP so
    # JP-CLINS Composition emit finds the 5 required sections
    # (admission_reason / admission_details / admission_diagnoses /
    # chief_complaint / present_illness) instead of the US 6-section set.
    section_list = spec.composition_sections_for(ctx.locale.upper())
    for section in section_list:
        builder = section_builders.get(section)
        if builder is not None:
            text, section_facts = builder(ctx)
            sections[section] = text
            facts.extend(section_facts)
        else:
            # Unknown section — generic fallback
            sections[section] = t("fallback.generic_fallback", ctx.target_lang)

    return NarrativeOutput(
        sections=sections,
        metadata={"generator": "template", "lang": ctx.target_lang},
        facts_used=facts,
    )
