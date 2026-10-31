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

from dataclasses import dataclass, field

from clinosim.codes.valuesets import concept_group

PATIENT_ICD_ALIASES: dict[str, tuple[str, ...]] = {
    name: concept_group(name).members
    for name in (
        "immunosuppressed",
        "CKD_baseline",
        "pre_existing_CKD",
        "pre_existing_heart_failure",
        "prior_heart_failure",
        "pre_existing_cardiac_disease",
        "liver_disease",
        "prior_depression",
        "severe_osteoporosis",
        "alcohol_etiology",
    )
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
        "aggressive_insulin_without_K_monitoring",
        "concurrent_antiplatelet",
        "concurrent_beta_blocker_and_ccb",
        "contrast_volume_high",
        "delayed_antibiotic",
        "excessive_IV_fluid",
        "excessive_diuresis",
        "high_vasopressor_dose",
        "massive_fluid_resuscitation",
        "multiple_transfusions",
        "nephrotoxic_drugs",
        "no_ppi",
        "no_reperfusion",
        "not_switched_to_D5_timely",
        "subtherapeutic_anticoagulation",
        "thrombolysis_given",
        "tpa_received",
        "triple_therapy",
        # devices / procedures / setting
        "cbd_exploration",
        "conversion_to_open",
        "ercp_performed",
        "ng_tube_high_output",
        "open_surgery",
        "procedure_recent",
        "prolonged_NPO",
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


@dataclass
class ComplicationContext:
    """Stay context for complication risk factors (Issue #2101): day indices
    of ICU transfer / intubation / surgery / first antibiotic, active
    medication and home-medication names (upper case), procedure types."""

    icu_day: int | None = None
    intubated_day: int | None = None
    surgery_day: int | None = None
    antibiotic_start_day: int | None = None
    medications: set[str] = field(default_factory=set)
    home_medications: set[str] = field(default_factory=set)
    procedure_types: set[str] = field(default_factory=set)
    dvt_prophylaxis: bool | None = None
    """Planned pharmacologic VTE prophylaxis (the prophylaxis module adds the
    order after the stay, so it is decided up front); None = unknown."""


DRUG_CLASSES: dict[str, tuple[str, ...]] = {
    "opioid": ("MORPHINE", "OXYCODONE", "HYDROMORPHONE", "FENTANYL", "TRAMADOL", "PENTAZOCINE"),
    "nsaid": ("IBUPROFEN", "KETOROLAC", "LOXOPROFEN", "NAPROXEN", "DICLOFENAC", "CELECOXIB"),
    "fluoroquinolone": ("LEVOFLOXACIN", "CIPROFLOXACIN", "MOXIFLOXACIN"),
    "clindamycin": ("CLINDAMYCIN",),
    "anticoagulant": (
        "HEPARIN",
        "ENOXAPARIN",
        "WARFARIN",
        "APIXABAN",
        "RIVAROXABAN",
        "DABIGATRAN",
        "EDOXABAN",
        "FONDAPARINUX",
    ),
    "therapeutic_anticoagulant": ("WARFARIN", "APIXABAN", "RIVAROXABAN", "DABIGATRAN", "EDOXABAN"),
    "heparin": ("HEPARIN",),
    "steroid": ("PREDNISOLONE", "PREDNISONE", "METHYLPREDNISOLONE", "HYDROCORTISONE", "DEXAMETHASONE"),
    "ppi": ("OMEPRAZOLE", "ESOMEPRAZOLE", "LANSOPRAZOLE", "PANTOPRAZOLE", "RABEPRAZOLE", "VONOPRAZAN"),
    "benzodiazepine": ("LORAZEPAM", "DIAZEPAM", "MIDAZOLAM", "CHLORDIAZEPOXIDE", "ALPRAZOLAM"),
    "diuretic": ("FUROSEMIDE", "TORSEMIDE", "BUMETANIDE", "HYDROCHLOROTHIAZIDE", "SPIRONOLACTONE"),
    "ace_inhibitor": ("LISINOPRIL", "ENALAPRIL", "RAMIPRIL", "CAPTOPRIL", "PERINDOPRIL", "IMIDAPRIL"),
    "antibiotic": (
        "CEFTRIAXONE",
        "CEFAZOLIN",
        "CEFEPIME",
        "CEFTAZIDIME",
        "MEROPENEM",
        "PIPERACILLIN",
        "AMPICILLIN",
        "VANCOMYCIN",
        "LEVOFLOXACIN",
        "CIPROFLOXACIN",
        "AZITHROMYCIN",
        "CLINDAMYCIN",
        "METRONIDAZOLE",
        "AMOXICILLIN",
        "DOXYCYCLINE",
        "SULFAMETHOXAZOLE",
    ),
}
"""Drug-name substrings per class for medication-exposure risk factors."""

# condition -> (kind, argument)
CONTEXT_RESOLVED: dict[str, tuple[str, str]] = {
    "icu_stay": ("since", "icu_day"),
    "icu_stay_over_7_days": ("over7", "icu_day"),
    "mechanical_ventilation": ("since", "intubated_day"),
    "intubation": ("since", "intubated_day"),
    "mechanical_ventilation_over_7_days": ("over7", "intubated_day"),
    "surgical_patient": ("since", "surgery_day"),
    "recent_surgery": ("since", "surgery_day"),
    "antibiotic_duration_over_7_days": ("over7", "antibiotic_start_day"),
    "broad_spectrum_antibiotic_over_7_days": ("over7", "antibiotic_start_day"),
    "opioid_use": ("drug", "opioid"),
    "NSAID_use": ("drug", "nsaid"),
    "fluoroquinolone_use": ("drug", "fluoroquinolone"),
    "clindamycin_use": ("drug", "clindamycin"),
    "anticoagulation": ("drug", "therapeutic_anticoagulant"),
    "anticoagulant_use": ("drug", "therapeutic_anticoagulant"),
    "unfractionated_heparin_use": ("drug", "heparin"),
    "corticosteroid_use": ("drug", "steroid"),
    "steroid_use": ("drug", "steroid"),
    "chronic_steroid_use": ("home_drug", "steroid"),
    "PPI_use": ("drug", "ppi"),
    "benzodiazepine_use": ("drug", "benzodiazepine"),
    "diuretic_use": ("drug", "diuretic"),
    "ACE_inhibitor_use": ("drug", "ace_inhibitor"),
    "no_dvt_prophylaxis": ("no_drug", "anticoagulant"),
    "no_pharmacologic_dvt_prophylaxis": ("no_drug", "anticoagulant"),
    "no_anticoagulation": ("no_drug", "anticoagulant"),
    "urinary_catheter": ("procedure", "urinary_catheter"),
    "indwelling_catheter": ("procedure", "urinary_catheter"),
    "central_line_present": ("procedure", "central_line"),
}
"""Context conditions resolved from :class:`ComplicationContext` (Issue #2101)."""


def resolve_context_condition(condition: str, ctx: ComplicationContext | None, day: int) -> bool:
    """Evaluate a :data:`CONTEXT_RESOLVED` condition; False without context."""
    if ctx is None:
        return False
    kind, arg = CONTEXT_RESOLVED[condition]
    if kind in ("since", "over7"):
        start = getattr(ctx, arg)
        if start is None:
            return False
        return day >= start if kind == "since" else day - start > 7
    if kind in ("drug", "no_drug", "home_drug"):
        names = ctx.home_medications if kind == "home_drug" else ctx.medications | ctx.home_medications
        present = any(sub in name for name in names for sub in DRUG_CLASSES[arg])
        if arg == "anticoagulant" and kind == "no_drug" and ctx.dvt_prophylaxis:
            present = True  # planned prophylaxis counts only against "no prophylaxis"
        return not present if kind == "no_drug" else present
    return arg in ctx.procedure_types
