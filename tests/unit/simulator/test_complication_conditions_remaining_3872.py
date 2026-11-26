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
    complication_diagnosis_code,
    complication_diagnosis_entries,
    non_diagnosis_tokens,
    pending_tokens,
)
from clinosim.simulator.complications import build_complication
from clinosim.simulator.delirium import delirium_rules

pytestmark = pytest.mark.unit

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
