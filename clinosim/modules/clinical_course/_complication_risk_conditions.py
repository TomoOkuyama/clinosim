"""Vocabulary for disease-YAML ``complications[].risk_factors[].condition`` (Issue #2093).

``_evaluate_risk_condition`` resolves a condition string in this order:

1. existing special forms (``age_over_N``, ``severity_severe``, ``immobility_days > n``,
   ``delirium_susceptibility`` / ``dvt_susceptibility > x``);
2. ``<state variable> <op> <number>`` for any canonical physiology state variable;
3. :data:`PATIENT_ICD_ALIASES` / :data:`STATE_ALIASES` / :data:`SEVERITY_ALIASES` below;
4. the patient-level vocabulary of ``clinosim.modules.disease.severity``
   (``dementia``, ``diabetes``, ``CKD``, ``obesity``, ...).

Strings that need stay or scenario context the complication evaluator does not
have yet (drug exposure, devices, procedures, imaging findings, disease
sub-types) are listed in :data:`CONTEXT_CONDITIONS`: they evaluate False by
design. Any other string is rejected by the unit test that scans every YAML,
so a typo can no longer silently disable a risk factor.
"""

from __future__ import annotations

PATIENT_ICD_ALIASES: dict[str, tuple[str, ...]] = {
    "CKD_baseline": ("N18",),
    "pre_existing_CKD": ("N18",),
    "pre_existing_heart_failure": ("I50",),
    "prior_heart_failure": ("I50",),
    "pre_existing_cardiac_disease": ("I50", "I25", "I21", "I48"),
    "liver_disease": ("K70", "K72", "K74", "K76"),
    "prior_depression": ("F32", "F33"),
    "severe_osteoporosis": ("M80", "M81"),
    "alcohol_etiology": ("F10",),
}
"""Condition names resolved from the patient's chronic problem list (ICD prefix)."""

IMMOBILITY_DEFAULT_DAYS: int = 2
"""Bare ``immobility``: bed-bound beyond the first two hospital days (same as
``immobility_days > 2``, the most common explicit form in the YAMLs)."""

MALNUTRITION_BMI_MAX: float = 18.5
"""``malnutrition`` / ``baseline_malnutrition``: BMI below the WHO underweight cut-off."""

STATE_ALIASES: dict[str, tuple[str, str, float]] = {
    "altered_consciousness": ("consciousness_impairment", ">=", 0.25),
    "reduced_consciousness": ("consciousness_impairment", ">=", 0.25),
    "decreased_consciousness": ("consciousness_impairment", ">=", 0.25),
    "GCS_below_10": ("consciousness_impairment", ">=", 0.5),
    "hypoxemia_severe": ("oxygenation_impairment", ">=", 0.35),
    "severe_dehydration": ("volume_status", "<=", -0.4),
    "volume_depleted": ("volume_status", "<=", -0.2),
    "renal_impairment": ("renal_function", "<", 0.6),
    "severe_inflammation": ("inflammation_level", ">", 0.6),
    "cardiogenic_shock": ("perfusion_status", "<", 0.3),
    "hyperglycemia": ("glucose_status", ">", 0.3),
}
"""Named conditions resolved from the day's physiological state. Consciousness
thresholds match the AVPU cut-offs (V at 0.25, P at 0.5)."""

SEVERITY_ALIASES: frozenset[str] = frozenset({"severe_DKA"})
"""Named conditions equivalent to ``severity_severe`` for the owning disease."""

CONTEXT_CONDITIONS: frozenset[str] = frozenset(
    {
        # drug exposure / treatment
        "ACE_inhibitor_use",
        "NSAID_use",
        "PPI_use",
        "aggressive_insulin_without_K_monitoring",
        "anticoagulant_use",
        "anticoagulation",
        "antibiotic_duration_over_7_days",
        "benzodiazepine_use",
        "broad_spectrum_antibiotic_over_7_days",
        "clindamycin_use",
        "concurrent_antiplatelet",
        "concurrent_beta_blocker_and_ccb",
        "contrast_volume_high",
        "corticosteroid_use",
        "delayed_antibiotic",
        "diuretic_use",
        "excessive_IV_fluid",
        "excessive_diuresis",
        "fluoroquinolone_use",
        "high_vasopressor_dose",
        "massive_fluid_resuscitation",
        "multiple_transfusions",
        "nephrotoxic_drugs",
        "no_anticoagulation",
        "no_dvt_prophylaxis",
        "no_pharmacologic_dvt_prophylaxis",
        "no_ppi",
        "no_reperfusion",
        "not_switched_to_D5_timely",
        "opioid_use",
        "steroid_use",
        "subtherapeutic_anticoagulation",
        "thrombolysis_given",
        "tpa_received",
        "triple_therapy",
        "unfractionated_heparin_use",
        "chronic_steroid_use",
        "immunosuppressed",
        # devices / procedures / setting
        "central_line_present",
        "cbd_exploration",
        "conversion_to_open",
        "ercp_performed",
        "icu_stay",
        "icu_stay_over_7_days",
        "indwelling_catheter",
        "intubation",
        "mechanical_ventilation",
        "mechanical_ventilation_over_7_days",
        "ng_tube_high_output",
        "open_surgery",
        "procedure_recent",
        "prolonged_NPO",
        "recent_surgery",
        "surgical_patient",
        "urinary_catheter",
        "no_preoperative_mrcp",
        "incomplete_appendectomy",
        "prior_vertebroplasty",
        # disease sub-type / imaging / exam findings
        "anterior_wall_MI",
        "brainstem_infarct",
        "choledocholithiasis",
        "closed_loop_obstruction",
        "cortical_infarct",
        "cortical_location",
        "emphysema_predominant",
        "free_floating_thrombus",
        "frontal_lobe_infarct",
        "gangrenous_cholecystitis",
        "hemiplegia",
        "hemorrhagic_transformation",
        "iliofemoral_dvt",
        "intraventricular_hemorrhage",
        "large_hematoma",
        "large_infarct_volume",
        "large_initial_volume",
        "large_mca_infarct",
        "large_or_bilateral_pe",
        "large_residual_dvt",
        "large_varices",
        "lower_limb_cellulitis",
        "massive_aspiration",
        "necrotizing_pancreatitis",
        "perforated_appendicitis",
        "pneumonia_as_source",
        "portal_hypertension",
        "portal_hypertension_severe",
        "proximal_dvt",
        "right_hemisphere_infarct",
        "right_heart_failure",
        "saddle_embolus",
        "spot_sign_on_CTA",
        "transmural_MI",
        "ulcer_with_visible_vessel",
        "unclear_anatomy",
        "variceal_source",
        "dysphagia",
        "severe_dysphagia",
        "thick_secretions",
        "urinary_obstruction",
        "urinary_retention",
        "oliguric",
        "rhabdomyolysis",
        "nephrotic_range_proteinuria",
        "severe_disability",
        "sepsis",
        "SBP",
        "infection",
        "hepatic_encephalopathy",
        "alcohol_withdrawal",
        "GI_bleeding",
        "hematemesis",
        "constipation",
        "vomiting",
        "vomiting_persistent",
        "active_vomiting",
        "poor_oral_intake",
        "electrolyte_imbalance",
        "hypercapnia",
        "hypercapnia_baseline",
        "polycythemia",
        "coagulopathy",
        "cardiogenic_shock_on_arrival",
        "treatment_resistant_archetype",
        "new_onset_T1DM",
        "first_MI",
        "EF_below_30",
        "EF_below_40",
        # lab-value thresholds not tied to a state variable
        "BUN_above_80",
        "BUN_above_100",
        "INR_above_2",
        "INR_above_2.5",
        "K_below_3.0_or_above_6.0",
        "Plt_below_50",
        "admission_K_below_4",
        "ascitic_protein_below_1",
        "baseline_K_low",
        "elevated_bilirubin",
        "elevated_bilirubin_at_admission",
        "hypokalemia",
        "hypomagnesemia",
        "hyponatremia_below_125",
        "hypophosphatemia",
        "pH_below_7.0",
        "severe_acidosis_pH_below_7.0",
        "rapid_glucose_drop_over_100_per_hour",
        # history / social
        "CHA2DS2_VASc_high",
        "injection_drug_use",
        "poor_dentition",
        "prior_cellulitis",
        "prior_gi_bleed",
        "prior_sbp",
        "prior_transfusion_reaction",
        "recurrent_dvt",
        "recurrent_pe",
        "social_isolation",
        "prior_icu_for_asthma",
        "pregnancy",
    }
)
"""Conditions that need stay / scenario context not yet available to the
complication evaluator; they evaluate False until that context is wired."""
