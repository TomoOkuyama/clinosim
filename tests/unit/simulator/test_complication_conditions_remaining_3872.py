"""The remaining disease-like in-hospital complications are Conditions (Issue #3872).

Extends the table of Issue #3673 to the disease-like tokens a JP cohort named
in discharge text without a Condition (hypoglycemia, C. difficile colitis,
potassium disorders, renal abscess, ...), and guards that every complication a
disease protocol can fire is classified: coded, a non-diagnosis event or a
named pending token.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest
import yaml

from clinosim.codes import code_exists, lookup
from clinosim.locale.loader import map_diagnosis_code
from clinosim.simulator.complication_dx import (
    complication_diagnoses,
    complication_diagnosis_code,
    non_diagnosis_tokens,
    pending_tokens,
)
from clinosim.simulator.complications import build_complication
from clinosim.simulator.delirium import delirium_rules

pytestmark = pytest.mark.unit


def complication_diagnosis_entries(complications, existing_codes):
    """The working-diagnosis entries for one list of the codes the stay carries."""
    return complication_diagnoses(complications, existing_codes)[0]


# token -> (US ICD-10-CM leaf, JP WHO ICD-10 code), each read in the CMS FY2027
# order file and the MHLW 基本分類表 (ICD-10 2013).
_ADDED = {
    "constipation_ileus": ("K59.00", "K59.0"),
    "hypoglycemia": ("E16.2", "E16.2"),
    "c_diff_colitis": ("A04.72", "A04.7"),
    "hypokalemia": ("E87.6", "E87.6"),
    "hyperkalemia": ("E87.5", "E87.5"),
    "steroid_hyperglycemia": ("R73.9", "R73.9"),
    "atrial_fibrillation_rvr": ("I48.91", "I48.9"),
    "renal_abscess": ("N15.1", "N15.1"),
    "seizure": ("R56.9", "R56.8"),
    "bacteremia": ("R78.81", "A49.9"),
    "cardiac_arrhythmia": ("I49.9", "I49.9"),
    "pressure_ulcer": ("L89.90", "L89.9"),
    "atelectasis": ("J98.11", "J98.1"),
    "venous_thromboembolism": ("I82.90", "I82.9"),
    "recurrent_aspiration": ("J69.0", "J69.0"),
}

# The remaining 69 tokens (second change of Issue #3872). Same sources, plus the
# CMS FY2027 tabular list and index (codes the index names: Fracture compression
# M48.50-, Dysfunction hepatic K76.89, Phlebitis leg deep I80.2-, ...). The JP
# code is the WHO ICD-10 (2013) code of the MHLW table.
_REMAINING = {
    "abscess_formation": ("L02.91", "L02.9"),
    "adhesive_bowel_obstruction": ("K56.50", "K56.5"),
    "adjacent_vertebral_fracture": ("M48.50XA", "M48.5"),
    "bacterial_superinfection": ("J15.9", "J15.9"),
    "bile_duct_injury": ("K91.71", "K91.8"),
    "bile_leak": ("K91.89", "K91.8"),
    "bleeding_uremic_platelet_dysfunction": ("D69.19", "D69.1"),
    "bowel_perforation": ("K63.1", "K63.1"),
    "brain_herniation": ("G93.5", "G93.5"),
    "burn_wound_infection": ("L08.9", "L08.9"),
    "cardioembolic_stroke": ("I63.40", "I63.4"),
    "central_line_associated_bloodstream_infection": ("T80.211A", "T80.2"),
    "cerebral_herniation": ("G93.5", "G93.5"),
    "cholangitis": ("K83.09", "K83.0"),
    "chronic_thromboembolic_pulmonary_hypertension": ("I27.24", "I27.2"),
    "coagulopathy_bleeding": ("D68.4", "D68.4"),
    "compartment_syndrome": ("T79.A0XA", "T79.6"),
    "critical_illness_polyneuropathy": ("G62.81", "G62.8"),
    "delirium_tremens": ("F10.231", "F10.4"),
    "dressler_syndrome": ("I24.1", "I24.1"),
    "electrolyte_imbalance": ("E87.8", "E87.8"),
    "empyema": ("J86.9", "J86.9"),
    "gi_bleeding": ("K92.2", "K92.2"),
    "hemorrhagic_shock": ("R57.8", "R57.8"),
    "hemorrhagic_transformation": ("I61.9", "I61.9"),
    "heparin_induced_thrombocytopenia": ("D75.822", "D75.8"),
    "hepatic_dysfunction": ("K76.89", "K76.8"),
    "hepatic_encephalopathy": ("K76.82", "K72.9"),
    "hepatic_encephalopathy_worsening": ("K76.82", "K72.9"),
    "hydrocephalus": ("G91.1", "G91.1"),
    "infected_necrosis": ("K85.92", "K85.9"),
    "inhalation_injury_respiratory_failure": ("J70.5", "J70.8"),
    "intra_abdominal_abscess": ("K65.1", "K65.0"),
    "lung_abscess": ("J85.1", "J85.1"),
    "lymphedema": ("I89.0", "I89.0"),
    "malnutrition_worsening": ("E46", "E46"),
    "median_nerve_dysfunction": ("G56.10", "G56.1"),
    "metabolic_acidosis": ("E87.21", "E87.2"),
    "myocarditis": ("J11.82", "J11.8"),
    "necrotizing_fasciitis": ("M72.6", "M72.6"),
    "pancreatic_duct_disruption": ("K86.89", "K86.8"),
    "pancreatic_pseudocyst": ("K86.3", "K86.3"),
    "parapneumonic_effusion": ("J91.8", "J91"),
    "pericarditis": ("I24.1", "I24.1"),
    "peritonitis": ("K65.9", "K65.9"),
    "phlegmasia_cerulea_dolens": ("I80.209", "I80.2"),
    "post_stroke_depression": ("F06.31", "F06.3"),
    "post_thrombotic_syndrome": ("I87.009", "I87.0"),
    "postoperative_ileus": ("K91.89", "K91.8"),
    "postoperative_pancreatitis": ("K85.90", "K85.9"),
    "pulmonary_edema": ("J81.0", "J81"),
    "recurrent_hematoma": ("S06.5XAA", "S06.5"),
    "retained_cbd_stone": ("K80.51", "K80.5"),
    "rhabdomyolysis": ("M62.82", "M62.8"),
    "rhabdomyolysis_aki": ("M62.82", "M62.8"),
    "right_heart_failure": ("I50.811", "I50.0"),
    "splenic_vein_thrombosis": ("I82.890", "I82.8"),
    "spontaneous_bacterial_peritonitis": ("K65.2", "K65.0"),
    "stress_cardiomyopathy": ("I51.81", "I51.8"),
    "stroke": ("I63.40", "I63.4"),
    "stump_appendicitis": ("K35.80", "K35.8"),
    "surgical_site_infection": ("T81.40XA", "T81.4"),
    "uremic_encephalopathy": ("G93.41", "G93.4"),
    "variceal_hemorrhage": ("I85.11", "I85.0"),
    "ventricular_arrhythmia": ("I47.20", "I47.2"),
    "viral_pneumonia": ("J12.9", "J12.9"),
    "withdrawal_seizure": ("R56.9", "R56.8"),
    "wound_dehiscence": ("T81.31XA", "T81.3"),
    "wound_infection": ("T81.49XA", "T81.4"),
}
_ADDED.update(_REMAINING)


@pytest.mark.parametrize(("token", "codes"), sorted(_ADDED.items()))
def test_added_token_is_coded_and_registered_in_both_systems(token: str, codes: tuple[str, str]) -> None:
    us, jp = codes
    assert complication_diagnosis_code(token) == us
    assert map_diagnosis_code(us, "US") == us
    assert map_diagnosis_code(us, "JP") == jp
    assert code_exists("icd-10-cm", us, exact=True)
    assert code_exists("icd-10", jp, exact=True)
    assert lookup("icd-10-cm", us, "en")
    assert lookup("icd-10", jp, "ja")  # a natural Japanese display, not the code


def _event(token: str, day: int) -> dict:
    return build_complication(token, day, f"2026-06-{10 + day:02d}T12:00:00", "daily_loop")


def test_hypoglycemia_is_not_swallowed_by_the_diabetes_category() -> None:
    """A diabetic stay carries E11.x; hypoglycemia is E16.x, a different category."""
    entries = complication_diagnosis_entries([_event("hypoglycemia", 2)], existing_codes=["E11.1", "E11.9"])
    assert [e["disease_id"] for e in entries] == ["E16.2"]


def test_potassium_disorders_share_a_category_but_both_are_kept() -> None:
    entries = complication_diagnosis_entries(
        [_event("hypokalemia", 2), _event("hyperkalemia", 4), _event("hypokalemia", 6)], existing_codes=[]
    )
    assert [(e["disease_id"], e["onset_day"]) for e in entries] == [("E87.6", 2), ("E87.5", 4)]


def test_a_category_the_stay_already_carries_still_blocks_the_other_tokens() -> None:
    """The first-onset-per-category rule is unchanged outside the full-code categories."""
    assert complication_diagnosis_entries([_event("atelectasis", 2)], existing_codes=["J98.1"]) == []
    assert complication_diagnosis_entries([_event("pressure_ulcer", 3)], existing_codes=["L89.1"]) == []


def test_a_known_potassium_code_blocks_only_itself() -> None:
    entries = complication_diagnosis_entries(
        [_event("hypokalemia", 2), _event("hyperkalemia", 3)], existing_codes=["E87.6"]
    )
    assert [e["disease_id"] for e in entries] == ["E87.5"]


def test_non_diagnosis_events_stay_procedures_and_findings() -> None:
    assert complication_diagnosis_entries([_event("intubation_required", 2)], existing_codes=[]) == []
    assert "intubation_required" in non_diagnosis_tokens()
    # "urosepsis" is a nonspecific term with no default code (ICD-10-CM Official
    # Guidelines FY2027 I.C.1.d.1.a(ii)); it is not coded as sepsis.
    assert complication_diagnosis_code("urosepsis") == ""
    assert "urosepsis" in non_diagnosis_tokens()


# --- the classification guard ------------------------------------------------

_PROTOCOLS = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "disease" / "reference_data"


def _declared_tokens() -> set[str]:
    tokens: set[str] = set()
    for f in glob.glob(str(_PROTOCOLS / "*.yaml")):
        data = yaml.safe_load(Path(f).read_text(encoding="utf-8")) or {}
        for entry in data.get("complications") or []:
            if isinstance(entry, dict) and entry.get("name"):
                tokens.add(str(entry["name"]))
    return tokens


def test_every_declared_token_is_coded_or_explicitly_classified() -> None:
    delirium = set(delirium_rules().existing_names)
    unclassified = sorted(
        t
        for t in _declared_tokens()
        if t not in delirium
        and not complication_diagnosis_code(t)
        and t not in non_diagnosis_tokens()
        and t not in pending_tokens()
    )
    assert not unclassified, unclassified


def test_the_classes_do_not_overlap_and_name_real_tokens() -> None:
    declared = _declared_tokens()
    coded = {t for t in declared if complication_diagnosis_code(t) and t not in delirium_rules().existing_names}
    assert not coded & non_diagnosis_tokens()
    assert not coded & pending_tokens()
    assert not non_diagnosis_tokens() & pending_tokens()
    assert (non_diagnosis_tokens() | pending_tokens()) <= declared


def test_the_added_tokens_left_the_pending_list() -> None:
    assert not set(_ADDED) & pending_tokens()


def test_no_token_is_pending_any_more() -> None:
    assert pending_tokens() == frozenset()


def test_synonym_tokens_share_one_code() -> None:
    for group in (
        ("brain_herniation", "cerebral_herniation"),
        ("rhabdomyolysis", "rhabdomyolysis_aki"),
        ("hepatic_encephalopathy", "hepatic_encephalopathy_worsening"),
        ("stroke", "cardioembolic_stroke"),
        ("pericarditis", "dressler_syndrome"),
    ):
        assert len({complication_diagnosis_code(t) for t in group}) == 1, group


def test_each_code_of_a_distinct_category_keeps_its_own_entry() -> None:
    """Alcohol withdrawal delirium (F10.231) is a different diagnosis from the stay's
    F10.23x withdrawal; a wound infection, a wound dehiscence and the other T81 codes
    are different postprocedural diagnoses; a pancreatic pseudocyst and a duct
    disruption are different K86 diagnoses."""
    entries = complication_diagnosis_entries([_event("delirium_tremens", 2)], existing_codes=["F10.239"])
    assert [e["disease_id"] for e in entries] == ["F10.231"]
    entries = complication_diagnosis_entries(
        [_event("surgical_site_infection", 3), _event("wound_dehiscence", 5)], existing_codes=[]
    )
    assert [e["disease_id"] for e in entries] == ["T81.40XA", "T81.31XA"]
    entries = complication_diagnosis_entries(
        [_event("pancreatic_pseudocyst", 9), _event("pancreatic_duct_disruption", 11)], existing_codes=["K85.1"]
    )
    assert [e["disease_id"] for e in entries] == ["K86.3", "K86.89"]
    # a stay that already carries that exact code is not given it twice
    assert complication_diagnosis_entries([_event("delirium_tremens", 2)], existing_codes=["F10.231"]) == []


def test_a_complication_of_the_stays_own_disease_category_is_not_a_second_diagnosis() -> None:
    """A recurrence or a worsening of the disease the stay carries (recurrent subdural
    hematoma, stump appendicitis, pancreatitis with infected necrosis) adds no
    Condition: the stay's diagnosis already names it."""
    assert complication_diagnosis_entries([_event("recurrent_hematoma", 5)], existing_codes=["S06.5"]) == []
    assert complication_diagnosis_entries([_event("stump_appendicitis", 9)], existing_codes=["K35.80"]) == []
    assert complication_diagnosis_entries([_event("infected_necrosis", 9)], existing_codes=["K85.1"]) == []
