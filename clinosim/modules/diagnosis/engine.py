"""Diagnosis engine — v0.1-beta: Bayesian differential diagnosis.

Maintains a probability distribution over candidate diagnoses and
updates via likelihood ratios as test results arrive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DiagnosisCandidate:
    disease_code: str
    icd_code: str
    display_name: str
    probability: float
    evidence: list[str] = field(default_factory=list)


@dataclass
class DifferentialDiagnosis:
    candidates: list[DiagnosisCandidate] = field(default_factory=list)
    working_diagnosis: str | None = None
    confirmed: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def top_candidate(self) -> DiagnosisCandidate | None:
        return self.candidates[0] if self.candidates else None


# Disease-specific differentials
DIFFERENTIALS: dict[str, list[dict]] = {
    "bacterial_pneumonia": [
        {"disease": "bacterial_pneumonia", "icd": "J18.9", "name": "Bacterial pneumonia", "prior": 0.45},
        {"disease": "viral_pneumonia", "icd": "J12.9", "name": "Viral pneumonia", "prior": 0.15},
        {"disease": "influenza", "icd": "J11.1", "name": "Influenza", "prior": 0.10},
        {"disease": "heart_failure", "icd": "I50.9", "name": "Heart failure (pulmonary edema)", "prior": 0.10},
        {"disease": "pulmonary_embolism", "icd": "I26.9", "name": "Pulmonary embolism", "prior": 0.05},
        {"disease": "tuberculosis", "icd": "A15.0", "name": "Tuberculosis", "prior": 0.02},
        {"disease": "other", "icd": "R05", "name": "Other respiratory", "prior": 0.13},
    ],
    "heart_failure_exacerbation": [
        {"disease": "heart_failure_exacerbation", "icd": "I50.9", "name": "Heart failure exacerbation", "prior": 0.55},
        {"disease": "pneumonia", "icd": "J18.9", "name": "Pneumonia", "prior": 0.15},
        {"disease": "acute_coronary_syndrome", "icd": "I21.9", "name": "Acute coronary syndrome", "prior": 0.10},
        {"disease": "pulmonary_embolism", "icd": "I26.9", "name": "Pulmonary embolism", "prior": 0.05},
        {"disease": "copd_exacerbation", "icd": "J44.1", "name": "COPD exacerbation", "prior": 0.05},
        {"disease": "other", "icd": "R06.0", "name": "Other dyspnea", "prior": 0.10},
    ],
    "hip_fracture": [
        {"disease": "hip_fracture", "icd": "S72.0", "name": "Hip fracture", "prior": 0.85},
        {"disease": "pathological_fracture", "icd": "M84.4", "name": "Pathological fracture (tumor)", "prior": 0.05},
        {"disease": "pelvic_fracture", "icd": "S32.1", "name": "Pelvic fracture", "prior": 0.05},
        {"disease": "other", "icd": "M79.6", "name": "Other hip pain", "prior": 0.05},
    ],
    "urinary_tract_infection": [
        {"disease": "urinary_tract_infection", "icd": "N39.0", "name": "Urinary tract infection", "prior": 0.50},
        {"disease": "pyelonephritis", "icd": "N10", "name": "Acute pyelonephritis", "prior": 0.25},
        {"disease": "nephrolithiasis", "icd": "N20.0", "name": "Nephrolithiasis", "prior": 0.08},
        {"disease": "prostatitis", "icd": "N41.0", "name": "Acute prostatitis", "prior": 0.05},
        {"disease": "cystitis", "icd": "N30.0", "name": "Acute cystitis", "prior": 0.07},
        {"disease": "other", "icd": "R30.0", "name": "Other urinary symptoms", "prior": 0.05},
    ],
    "copd_exacerbation": [
        {"disease": "copd_exacerbation", "icd": "J44.1", "name": "COPD with acute exacerbation", "prior": 0.50},
        {"disease": "pneumonia", "icd": "J18.9", "name": "Pneumonia", "prior": 0.20},
        {"disease": "heart_failure", "icd": "I50.9", "name": "Heart failure", "prior": 0.10},
        {"disease": "pulmonary_embolism", "icd": "I26.9", "name": "Pulmonary embolism", "prior": 0.05},
        {"disease": "pneumothorax", "icd": "J93.9", "name": "Pneumothorax", "prior": 0.03},
        {"disease": "other", "icd": "R06.0", "name": "Other dyspnea", "prior": 0.12},
    ],
    "sepsis": [
        {"disease": "sepsis", "icd": "A41.9", "name": "Sepsis, unspecified organism", "prior": 0.35},
        {"disease": "severe_sepsis", "icd": "R65.20", "name": "Severe sepsis without shock", "prior": 0.20},
        {"disease": "pneumonia_sirs", "icd": "J18.9", "name": "Pneumonia with SIRS", "prior": 0.15},
        {"disease": "uti_bacteremia", "icd": "N39.0", "name": "UTI with bacteremia", "prior": 0.10},
        {"disease": "intra_abdominal", "icd": "K65.9", "name": "Intra-abdominal infection", "prior": 0.08},
        {"disease": "endocarditis", "icd": "I33.0", "name": "Endocarditis", "prior": 0.03},
        {"disease": "other", "icd": "R65.10", "name": "Other SIRS", "prior": 0.09},
    ],
    "cerebral_infarction": [
        {"disease": "cerebral_infarction", "icd": "I63.9", "name": "Cerebral infarction", "prior": 0.55},
        {"disease": "hemorrhagic_stroke", "icd": "I61.9", "name": "Intracerebral hemorrhage", "prior": 0.15},
        {"disease": "tia", "icd": "G45.9", "name": "Transient ischemic attack", "prior": 0.10},
        {"disease": "brain_tumor", "icd": "C71.9", "name": "Brain neoplasm", "prior": 0.05},
        {"disease": "migraine_aura", "icd": "G43.1", "name": "Migraine with aura", "prior": 0.05},
        {"disease": "other", "icd": "R29.8", "name": "Other neurological symptoms", "prior": 0.10},
    ],
    "acute_mi": [
        {"disease": "acute_mi", "icd": "I21.9", "name": "Acute myocardial infarction", "prior": 0.50},
        {"disease": "unstable_angina", "icd": "I20.0", "name": "Unstable angina", "prior": 0.15},
        {"disease": "aortic_dissection", "icd": "I71.0", "name": "Aortic dissection", "prior": 0.05},
        {"disease": "pulmonary_embolism", "icd": "I26.9", "name": "Pulmonary embolism", "prior": 0.05},
        {"disease": "pericarditis", "icd": "I30.9", "name": "Acute pericarditis", "prior": 0.05},
        {"disease": "gerd", "icd": "K21.0", "name": "GERD with esophagitis", "prior": 0.10},
        {"disease": "other", "icd": "R07.9", "name": "Other chest pain", "prior": 0.10},
    ],
    "gi_bleeding": [
        {"disease": "peptic_ulcer_bleed", "icd": "K25.4", "name": "Gastric ulcer with hemorrhage", "prior": 0.30},
        {"disease": "gi_bleeding", "icd": "K92.2", "name": "GI hemorrhage, unspecified", "prior": 0.20},
        {"disease": "variceal_bleed", "icd": "I85.0", "name": "Esophageal varices with bleeding", "prior": 0.10},
        {"disease": "diverticular_bleed", "icd": "K57.3", "name": "Diverticular disease with hemorrhage", "prior": 0.15},
        {"disease": "mallory_weiss", "icd": "K22.6", "name": "Mallory-Weiss tear", "prior": 0.08},
        {"disease": "gi_malignancy", "icd": "C16.9", "name": "GI malignancy", "prior": 0.07},
        {"disease": "other", "icd": "K92.9", "name": "Other GI disease", "prior": 0.10},
    ],
    "diabetic_ketoacidosis": [
        {"disease": "diabetic_ketoacidosis", "icd": "E11.10", "name": "DKA", "prior": 0.55},
        {"disease": "hhs", "icd": "E11.00", "name": "Hyperosmolar hyperglycemic state", "prior": 0.15},
        {"disease": "alcoholic_ketoacidosis", "icd": "E87.2", "name": "Alcoholic ketoacidosis", "prior": 0.05},
        {"disease": "lactic_acidosis", "icd": "E87.2", "name": "Lactic acidosis", "prior": 0.08},
        {"disease": "starvation_ketosis", "icd": "E87.2", "name": "Starvation ketosis", "prior": 0.05},
        {"disease": "other", "icd": "R73.9", "name": "Other hyperglycemia", "prior": 0.12},
    ],
    "ileus": [
        {"disease": "ileus", "icd": "K56.6", "name": "Intestinal obstruction", "prior": 0.50},
        {"disease": "paralytic_ileus", "icd": "K56.0", "name": "Paralytic ileus", "prior": 0.20},
        {"disease": "volvulus", "icd": "K56.2", "name": "Volvulus", "prior": 0.08},
        {"disease": "incarcerated_hernia", "icd": "K46.0", "name": "Incarcerated hernia", "prior": 0.10},
        {"disease": "other", "icd": "K56.9", "name": "Other intestinal obstruction", "prior": 0.12},
    ],
    "acute_pancreatitis": [
        {"disease": "acute_pancreatitis", "icd": "K85.9", "name": "Acute pancreatitis", "prior": 0.60},
        {"disease": "gallstone_pancreatitis", "icd": "K85.1", "name": "Gallstone pancreatitis", "prior": 0.15},
        {"disease": "peptic_ulcer", "icd": "K25.9", "name": "Peptic ulcer", "prior": 0.08},
        {"disease": "cholecystitis", "icd": "K81.0", "name": "Acute cholecystitis", "prior": 0.07},
        {"disease": "other", "icd": "R10.1", "name": "Other epigastric pain", "prior": 0.10},
    ],
    "acute_appendicitis": [
        {"disease": "acute_appendicitis", "icd": "K35.80", "name": "Acute appendicitis", "prior": 0.65},
        {"disease": "mesenteric_lymphadenitis", "icd": "I88.0", "name": "Mesenteric lymphadenitis", "prior": 0.10},
        {"disease": "ovarian_cyst", "icd": "N83.2", "name": "Ovarian cyst", "prior": 0.08},
        {"disease": "crohns", "icd": "K50.9", "name": "Crohn's disease", "prior": 0.05},
        {"disease": "other", "icd": "R10.3", "name": "Other RLQ pain", "prior": 0.12},
    ],
    "pulmonary_embolism": [
        {"disease": "pulmonary_embolism", "icd": "I26.9", "name": "Pulmonary embolism", "prior": 0.45},
        {"disease": "pneumonia", "icd": "J18.9", "name": "Pneumonia", "prior": 0.15},
        {"disease": "heart_failure", "icd": "I50.9", "name": "Heart failure", "prior": 0.10},
        {"disease": "pneumothorax", "icd": "J93.9", "name": "Pneumothorax", "prior": 0.05},
        {"disease": "aortic_dissection", "icd": "I71.0", "name": "Aortic dissection", "prior": 0.05},
        {"disease": "other", "icd": "R06.0", "name": "Other dyspnea", "prior": 0.20},
    ],
    "acute_cholecystitis": [
        {"disease": "acute_cholecystitis", "icd": "K81.0", "name": "Acute cholecystitis", "prior": 0.60},
        {"disease": "biliary_colic", "icd": "K80.2", "name": "Biliary colic", "prior": 0.15},
        {"disease": "cholangitis", "icd": "K83.0", "name": "Cholangitis", "prior": 0.08},
        {"disease": "peptic_ulcer", "icd": "K25.9", "name": "Peptic ulcer", "prior": 0.07},
        {"disease": "other", "icd": "R10.1", "name": "Other RUQ pain", "prior": 0.10},
    ],
    "atrial_fibrillation_rvr": [
        {"disease": "atrial_fibrillation_rvr", "icd": "I48.91", "name": "Atrial fibrillation with RVR", "prior": 0.65},
        {"disease": "svt", "icd": "I47.1", "name": "Supraventricular tachycardia", "prior": 0.10},
        {"disease": "atrial_flutter", "icd": "I48.92", "name": "Atrial flutter", "prior": 0.10},
        {"disease": "thyrotoxicosis", "icd": "E05.9", "name": "Thyrotoxicosis", "prior": 0.05},
        {"disease": "other", "icd": "R00.0", "name": "Other tachycardia", "prior": 0.10},
    ],
    "cellulitis": [
        {"disease": "cellulitis", "icd": "L03.90", "name": "Cellulitis", "prior": 0.65},
        {"disease": "abscess", "icd": "L02.9", "name": "Cutaneous abscess", "prior": 0.10},
        {"disease": "dvt", "icd": "I80.2", "name": "DVT (leg swelling mimic)", "prior": 0.08},
        {"disease": "necrotizing_fasciitis", "icd": "M72.6", "name": "Necrotizing fasciitis", "prior": 0.03},
        {"disease": "other", "icd": "L08.9", "name": "Other skin infection", "prior": 0.14},
    ],
    "acute_kidney_injury": [
        {"disease": "acute_kidney_injury", "icd": "N17.9", "name": "Acute kidney injury", "prior": 0.55},
        {"disease": "prerenal_aki", "icd": "N17.9", "name": "Prerenal AKI (dehydration)", "prior": 0.20},
        {"disease": "ckd_exacerbation", "icd": "N18.9", "name": "CKD acute exacerbation", "prior": 0.10},
        {"disease": "obstructive_uropathy", "icd": "N13.9", "name": "Obstructive uropathy", "prior": 0.05},
        {"disease": "other", "icd": "N19", "name": "Other renal failure", "prior": 0.10},
    ],
    "liver_cirrhosis_decompensated": [
        {"disease": "liver_cirrhosis_decompensated", "icd": "K74.60", "name": "Decompensated cirrhosis", "prior": 0.50},
        {"disease": "alcoholic_hepatitis", "icd": "K70.1", "name": "Alcoholic hepatitis", "prior": 0.15},
        {"disease": "hepatic_encephalopathy", "icd": "K72.9", "name": "Hepatic encephalopathy", "prior": 0.15},
        {"disease": "sbp", "icd": "K65.0", "name": "Spontaneous bacterial peritonitis", "prior": 0.10},
        {"disease": "other", "icd": "K76.9", "name": "Other liver disease", "prior": 0.10},
    ],
    "aspiration_pneumonia": [
        {"disease": "aspiration_pneumonia", "icd": "J69.0", "name": "Aspiration pneumonia", "prior": 0.55},
        {"disease": "bacterial_pneumonia", "icd": "J18.9", "name": "Community-acquired pneumonia", "prior": 0.20},
        {"disease": "lung_abscess", "icd": "J85.1", "name": "Lung abscess", "prior": 0.05},
        {"disease": "chemical_pneumonitis", "icd": "J68.0", "name": "Chemical pneumonitis", "prior": 0.08},
        {"disease": "other", "icd": "J98.8", "name": "Other respiratory disorder", "prior": 0.12},
    ],
    "influenza": [
        {"disease": "influenza", "icd": "J10.1", "name": "Influenza with respiratory manifestations", "prior": 0.55},
        {"disease": "bacterial_pneumonia", "icd": "J18.9", "name": "Bacterial pneumonia", "prior": 0.20},
        {"disease": "viral_uri", "icd": "J06.9", "name": "Viral URI", "prior": 0.10},
        {"disease": "covid", "icd": "U07.1", "name": "COVID-19", "prior": 0.08},
        {"disease": "other", "icd": "R50.9", "name": "Fever, unspecified", "prior": 0.07},
    ],
    "asthma_exacerbation": [
        {"disease": "asthma_exacerbation", "icd": "J45.21", "name": "Acute severe asthma", "prior": 0.60},
        {"disease": "copd_exacerbation", "icd": "J44.1", "name": "COPD exacerbation", "prior": 0.15},
        {"disease": "pneumonia", "icd": "J18.9", "name": "Pneumonia", "prior": 0.08},
        {"disease": "heart_failure", "icd": "I50.9", "name": "Pulmonary edema", "prior": 0.07},
        {"disease": "other", "icd": "R06.2", "name": "Wheezing", "prior": 0.10},
    ],
    "hemorrhagic_stroke": [
        {"disease": "hemorrhagic_stroke", "icd": "I61.9", "name": "Intracerebral hemorrhage", "prior": 0.55},
        {"disease": "ischemic_stroke", "icd": "I63.9", "name": "Ischemic stroke", "prior": 0.20},
        {"disease": "subarachnoid_hemorrhage", "icd": "I60.9", "name": "Subarachnoid hemorrhage", "prior": 0.10},
        {"disease": "brain_tumor", "icd": "C71.9", "name": "Brain neoplasm", "prior": 0.05},
        {"disease": "other", "icd": "R29.8", "name": "Other neurological", "prior": 0.10},
    ],
    "vertebral_compression_fracture": [
        {"disease": "vertebral_compression_fracture", "icd": "M80.08", "name": "Pathological vertebral fracture", "prior": 0.65},
        {"disease": "spinal_metastasis", "icd": "C79.5", "name": "Spinal metastasis", "prior": 0.10},
        {"disease": "disc_herniation", "icd": "M51.1", "name": "Disc herniation", "prior": 0.10},
        {"disease": "other", "icd": "M54.5", "name": "Low back pain", "prior": 0.15},
    ],
    "deep_vein_thrombosis": [
        {"disease": "deep_vein_thrombosis", "icd": "I80.20", "name": "DVT lower extremity", "prior": 0.55},
        {"disease": "cellulitis", "icd": "L03.11", "name": "Cellulitis (mimic)", "prior": 0.15},
        {"disease": "baker_cyst", "icd": "M71.20", "name": "Baker cyst rupture", "prior": 0.08},
        {"disease": "muscle_strain", "icd": "S86.9", "name": "Muscle strain", "prior": 0.10},
        {"disease": "other", "icd": "M79.6", "name": "Other limb pain", "prior": 0.12},
    ],
    "traffic_accident_severe": [
        {"disease": "multiple_trauma", "icd": "T07", "name": "Multiple injuries", "prior": 0.50},
        {"disease": "rib_fracture", "icd": "S22.4", "name": "Multiple rib fractures", "prior": 0.15},
        {"disease": "spleen_laceration", "icd": "S36.0", "name": "Splenic laceration", "prior": 0.10},
        {"disease": "pneumothorax", "icd": "S27.0", "name": "Traumatic pneumothorax", "prior": 0.08},
        {"disease": "other", "icd": "T14.9", "name": "Injury, unspecified", "prior": 0.17},
    ],
    "wrist_fracture_surgical": [
        {"disease": "distal_radius_fracture", "icd": "S52.50", "name": "Distal radius fracture", "prior": 0.75},
        {"disease": "scaphoid_fracture", "icd": "S62.0", "name": "Scaphoid fracture", "prior": 0.10},
        {"disease": "other", "icd": "S52.9", "name": "Other forearm fracture", "prior": 0.15},
    ],
    "subdural_hematoma": [
        {"disease": "subdural_hematoma", "icd": "S06.5", "name": "Traumatic subdural hemorrhage", "prior": 0.60},
        {"disease": "epidural_hematoma", "icd": "S06.4", "name": "Epidural hemorrhage", "prior": 0.10},
        {"disease": "cerebral_contusion", "icd": "S06.3", "name": "Cerebral contusion", "prior": 0.15},
        {"disease": "other", "icd": "S06.9", "name": "Other intracranial injury", "prior": 0.15},
    ],
}

# Diagnosis code progression (more specific as confidence grows)
DIAGNOSIS_PROGRESSION: dict[str, list[tuple[float, str, str]]] = {
    "bacterial_pneumonia": [
        (0.0, "J18.9", "Pneumonia, unspecified"),
        (0.7, "J18.1", "Lobar pneumonia, unspecified"),
        (0.9, "J13", "Pneumonia due to Streptococcus pneumoniae"),
    ],
    "heart_failure_exacerbation": [
        (0.0, "I50.9", "Heart failure, unspecified"),
        (0.7, "I50.0", "Congestive heart failure"),
        (0.9, "I50.0", "Congestive heart failure, acute exacerbation"),
    ],
    "hip_fracture": [
        (0.0, "S72.0", "Fracture of neck of femur"),
        (0.7, "S72.00", "Fracture of neck of femur, closed"),
        (0.9, "S72.00", "Fracture of neck of femur, closed"),
    ],
    "urinary_tract_infection": [
        (0.0, "N39.0", "Urinary tract infection, site not specified"),
        (0.7, "N10", "Acute tubulo-interstitial nephritis (pyelonephritis)"),
        (0.9, "N10", "Acute pyelonephritis"),
    ],
    "copd_exacerbation": [
        (0.0, "J44.1", "COPD with acute exacerbation"),
        (0.7, "J44.1", "COPD with acute exacerbation"),
        (0.9, "J44.0", "COPD with acute lower respiratory infection"),
    ],
    "sepsis": [
        (0.0, "A41.9", "Sepsis, unspecified organism"),
        (0.7, "R65.20", "Severe sepsis without septic shock"),
        (0.9, "R65.21", "Severe sepsis with septic shock"),
    ],
    "cerebral_infarction": [
        (0.0, "I63.9", "Cerebral infarction, unspecified"),
        (0.7, "I63.3", "Cerebral infarction due to thrombosis of cerebral arteries"),
        (0.9, "I63.3", "Cerebral infarction, MCA territory"),
    ],
    "acute_mi": [
        (0.0, "I21.9", "Acute myocardial infarction, unspecified"),
        (0.7, "I21.0", "Acute transmural MI of anterior wall"),
        (0.9, "I21.0", "STEMI, anterior wall"),
    ],
    "gi_bleeding": [
        (0.0, "K92.2", "Gastrointestinal hemorrhage, unspecified"),
        (0.7, "K25.4", "Acute gastric ulcer with hemorrhage"),
        (0.9, "K25.4", "Gastric ulcer with hemorrhage"),
    ],
    "diabetic_ketoacidosis": [
        (0.0, "E11.65", "Type 2 DM with hyperglycemia"),
        (0.7, "E11.10", "Type 2 DM with ketoacidosis without coma"),
        (0.9, "E11.10", "Diabetic ketoacidosis"),
    ],
    "ileus": [
        (0.0, "K56.9", "Intestinal obstruction, unspecified"),
        (0.7, "K56.6", "Other intestinal obstruction"),
        (0.9, "K56.6", "Adhesive intestinal obstruction"),
    ],
    "acute_pancreatitis": [
        (0.0, "K85.9", "Acute pancreatitis, unspecified"),
        (0.7, "K85.1", "Biliary acute pancreatitis"),
        (0.9, "K85.1", "Gallstone pancreatitis"),
    ],
    "acute_appendicitis": [
        (0.0, "K37", "Unspecified appendicitis"),
        (0.7, "K35.80", "Acute appendicitis"),
        (0.9, "K35.2", "Acute appendicitis with peritonitis"),
    ],
    "pulmonary_embolism": [
        (0.0, "I26.9", "Pulmonary embolism without acute cor pulmonale"),
        (0.7, "I26.9", "Pulmonary embolism"),
        (0.9, "I26.0", "Pulmonary embolism with acute cor pulmonale"),
    ],
    "acute_cholecystitis": [
        (0.0, "K81.9", "Cholecystitis, unspecified"),
        (0.7, "K81.0", "Acute cholecystitis"),
        (0.9, "K80.0", "Calculus of gallbladder with acute cholecystitis"),
    ],
    "atrial_fibrillation_rvr": [
        (0.0, "I48.91", "Unspecified atrial fibrillation"),
        (0.7, "I48.0", "Paroxysmal atrial fibrillation"),
        (0.9, "I48.1", "Persistent atrial fibrillation"),
    ],
    "cellulitis": [
        (0.0, "L03.90", "Cellulitis, unspecified"),
        (0.7, "L03.11", "Cellulitis of right lower limb"),
        (0.9, "L03.11", "Cellulitis of lower limb"),
    ],
    "acute_kidney_injury": [
        (0.0, "N17.9", "Acute kidney failure, unspecified"),
        (0.7, "N17.0", "Acute kidney failure with tubular necrosis"),
        (0.9, "N17.0", "Acute tubular necrosis"),
    ],
    "liver_cirrhosis_decompensated": [
        (0.0, "K74.60", "Unspecified cirrhosis of liver"),
        (0.7, "K70.31", "Alcoholic cirrhosis with ascites"),
        (0.9, "K74.60", "Decompensated cirrhosis"),
    ],
    "aspiration_pneumonia": [
        (0.0, "J69.0", "Pneumonitis due to food and vomit"),
        (0.7, "J69.0", "Aspiration pneumonia"),
        (0.9, "J69.0", "Aspiration pneumonia"),
    ],
    "influenza": [
        (0.0, "J11.1", "Influenza, unspecified, with respiratory manifestations"),
        (0.7, "J10.1", "Influenza due to identified virus"),
        (0.9, "J10.0", "Influenza with pneumonia"),
    ],
    "asthma_exacerbation": [
        (0.0, "J45.9", "Asthma, unspecified"),
        (0.7, "J45.21", "Mild intermittent asthma with acute exacerbation"),
        (0.9, "J45.41", "Moderate persistent asthma with acute exacerbation"),
    ],
    "hemorrhagic_stroke": [
        (0.0, "I61.9", "Nontraumatic intracerebral hemorrhage, unspecified"),
        (0.7, "I61.0", "Nontraumatic intracerebral hemorrhage, hemispheric"),
        (0.9, "I61.0", "Hemorrhagic stroke, hemispheric"),
    ],
    "vertebral_compression_fracture": [
        (0.0, "M48.50", "Collapsed vertebra, site unspecified"),
        (0.7, "M80.08", "Age-related osteoporosis with pathological fracture"),
        (0.9, "M80.08", "Osteoporotic vertebral compression fracture"),
    ],
    "deep_vein_thrombosis": [
        (0.0, "I82.90", "Embolism and thrombosis of unspecified vein"),
        (0.7, "I80.20", "Phlebitis and thrombophlebitis of lower extremity"),
        (0.9, "I80.20", "Deep vein thrombosis, lower extremity"),
    ],
}

# Keep backward compatibility
DEFAULT_PNEUMONIA_DIFFERENTIAL = DIFFERENTIALS["bacterial_pneumonia"]

# Likelihood ratios for key findings
LR_TABLE: dict[str, dict[str, dict[str, float]]] = {
    "chest_xray_consolidation": {
        "bacterial_pneumonia": {"pos": 8.0, "neg": 0.3},
        "viral_pneumonia": {"pos": 2.0, "neg": 0.7},
        "heart_failure": {"pos": 0.5, "neg": 1.1},
    },
    "procalcitonin_elevated": {
        "bacterial_pneumonia": {"pos": 6.0, "neg": 0.15},
        "viral_pneumonia": {"pos": 0.3, "neg": 2.0},
    },
    "crp_above_100": {
        "bacterial_pneumonia": {"pos": 3.5, "neg": 0.4},
        "viral_pneumonia": {"pos": 0.5, "neg": 1.5},
    },
    "wbc_elevated": {
        "bacterial_pneumonia": {"pos": 2.5, "neg": 0.6},
        "viral_pneumonia": {"pos": 0.5, "neg": 1.3},
    },
}

def initialize_differential(
    disease_id: str = "bacterial_pneumonia",
    age: int = 70,
    protocol_diagnostic: dict | None = None,
) -> DifferentialDiagnosis:
    """Create initial differential. Uses protocol YAML data if provided, falls back to built-in.

    Args:
        protocol_diagnostic: The 'diagnostic' section from disease YAML.
            If provided, uses protocol_diagnostic['differential'] and protocol_diagnostic['diagnosis_progression'].
    """
    # Prefer protocol YAML data, fall back to built-in
    if protocol_diagnostic and "differential" in protocol_diagnostic:
        differential_list = protocol_diagnostic["differential"]
    else:
        differential_list = DIFFERENTIALS.get(disease_id, DEFAULT_PNEUMONIA_DIFFERENTIAL)
    candidates = []
    for dx in differential_list:
        prior = dx["prior"]
        # Age adjustment: elderly → higher probability of HF overlap
        if age >= 75 and dx["disease"] == "heart_failure":
            prior *= 1.5
        candidates.append(DiagnosisCandidate(
            disease_code=dx["disease"],
            icd_code=dx["icd"],
            display_name=dx["name"],
            probability=prior,
        ))

    # Normalize
    total = sum(c.probability for c in candidates)
    for c in candidates:
        c.probability /= total

    candidates.sort(key=lambda c: -c.probability)

    diff = DifferentialDiagnosis(candidates=candidates)
    if candidates[0].probability > 0.5:
        diff.working_diagnosis = candidates[0].disease_code
    return diff


def update_differential(
    diff: DifferentialDiagnosis,
    findings: list[tuple[str, bool]],
    confirmation_threshold: float = 0.90,
    protocol_lr_table: dict | None = None,
) -> DifferentialDiagnosis:
    """Update differential with new findings via Bayesian update.

    Args:
        diff: Current differential
        protocol_lr_table: LR table from disease YAML. Falls back to built-in LR_TABLE.
        findings: List of (finding_name, is_positive) tuples
        confirmation_threshold: Probability at which diagnosis is confirmed
    """
    for finding_name, is_positive in findings:
        effective_lr = protocol_lr_table or LR_TABLE
        lr_entry = effective_lr.get(finding_name)
        if lr_entry is None:
            continue

        for candidate in diff.candidates:
            dx = candidate.disease_code
            if dx in lr_entry:
                dx_lr = lr_entry[dx]
                if is_positive:
                    lr = dx_lr.get("pos", dx_lr.get("positive_LR", 1.0))
                else:
                    lr = dx_lr.get("neg", dx_lr.get("negative_LR", 1.0))
                candidate.probability *= lr
                candidate.evidence.append(
                    f"{finding_name}: {'(+)' if is_positive else '(-)'} LR={lr}"
                )

    # Normalize
    total = sum(c.probability for c in diff.candidates)
    if total > 0:
        for c in diff.candidates:
            c.probability /= total

    # Sort
    diff.candidates.sort(key=lambda c: -c.probability)

    # Check confirmation
    top = diff.candidates[0]
    if top.probability >= confirmation_threshold:
        diff.confirmed = True
        diff.working_diagnosis = top.disease_code
    elif top.probability >= 0.5:
        diff.working_diagnosis = top.disease_code

    diff.timestamp = datetime.now()
    return diff


def get_current_diagnosis_code(
    diff: DifferentialDiagnosis,
    protocol_progression: dict | None = None,
) -> tuple[str, str]:
    """Returns (ICD code, display name) based on current confidence.

    Args:
        protocol_progression: diagnosis_progression from disease YAML. Falls back to built-in.
    """
    if not diff.working_diagnosis:
        return "R05", "Cough, unspecified"

    # Prefer protocol YAML, fall back to built-in
    if protocol_progression and diff.working_diagnosis in protocol_progression:
        progression = protocol_progression[diff.working_diagnosis]
    else:
        progression = DIAGNOSIS_PROGRESSION.get(diff.working_diagnosis)
    if not progression:
        top = diff.top_candidate
        return (top.icd_code, top.display_name) if top else ("R05", "Cough")

    confidence = diff.top_candidate.probability if diff.top_candidate else 0
    code, name = progression[0][1], progression[0][2]
    for threshold, c, n in progression:
        if confidence >= threshold:
            code, name = c, n
    return code, name
