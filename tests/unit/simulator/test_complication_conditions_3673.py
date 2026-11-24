"""In-hospital complications are dated Conditions of the stay (Issue #3673).

A complication that names a diagnosis (acute kidney injury, deep vein
thrombosis, ...) becomes a ``working_diagnoses`` entry with the onset of the
complication, so the Condition, ``Encounter.diagnosis`` and the discharge
summary agree with the narrated course. A complication with no diagnosis code
stays a narrative-only event.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import pytest
import yaml

from clinosim.codes import code_exists
from clinosim.locale.loader import map_diagnosis_code
from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions
from clinosim.simulator.complication_dx import (
    complication_diagnosis_code,
    complication_diagnosis_codes,
    complication_diagnosis_entries,
)
from clinosim.simulator.complications import build_complication
from clinosim.simulator.delirium import delirium_rules

pytestmark = pytest.mark.unit

_AKI = build_complication("acute_kidney_injury", 6, "2026-06-20T12:00:00", "daily_loop")
_DVT = build_complication("dvt", 4, "2026-06-18T12:00:00", "daily_loop")
_DELIRIUM = build_complication("delirium", 1, "2026-06-15T12:00:00", "derived_from_consciousness")
_INTUBATION = build_complication("intubation_required", 2, "2026-06-16T12:00:00", "daily_loop")


def test_coded_complications_become_dated_entries() -> None:
    entries = complication_diagnosis_entries([_AKI, _DVT], existing_codes=[])
    assert entries == [
        {
            "disease_id": "N17.9",
            "onset_day": 6,
            "onset_datetime": "2026-06-20T12:00:00",
            "source": "in_hospital_complication",
        },
        {
            "disease_id": "I82.40",
            "onset_day": 4,
            "onset_datetime": "2026-06-18T12:00:00",
            "source": "in_hospital_complication",
        },
    ]


def test_uncoded_complication_emits_nothing() -> None:
    assert complication_diagnosis_entries([_INTUBATION], existing_codes=[]) == []
    assert complication_diagnosis_code("intubation_required") == ""


def test_code_the_stay_already_carries_is_not_duplicated() -> None:
    assert complication_diagnosis_entries([_AKI], existing_codes=["N17.9"]) == []
    # The same 3-character category counts (AKI N17.0 already coded).
    assert complication_diagnosis_entries([_AKI], existing_codes=["N17.0"]) == []
    assert complication_diagnosis_entries([_AKI], existing_codes=["N18.3"]) != []


def test_one_entry_per_code_first_onset_wins() -> None:
    again = build_complication("acute_kidney_injury", 9, "2026-06-23T12:00:00", "daily_loop")
    entries = complication_diagnosis_entries([_AKI, again], existing_codes=[])
    assert [e["onset_day"] for e in entries] == [6]


def test_delirium_entry_carries_the_complication_onset() -> None:
    [entry] = complication_diagnosis_entries([_DELIRIUM], existing_codes=[])
    assert entry["disease_id"] == "F05"
    assert entry["onset_datetime"] == "2026-06-15T12:00:00"
    assert entry["onset_day"] == 1


def test_new_disease_complication_is_not_doubled() -> None:
    """A disease that started in hospital already has its own entry."""
    new = build_complication("acute_kidney_injury", 3, "2026-06-17T12:00:00", "in_hospital_new_disease")
    assert complication_diagnosis_entries([new], existing_codes=[]) == []


def _record(entries: list[dict], secondary: list[str] | None = None) -> dict:
    return {
        "patient": {"patient_id": "POP-000042", "sex": "M"},
        "clinical_diagnosis": {
            "admission_diagnosis_code": "J44.1",
            "discharge_diagnosis_code": "J44.1",
            "working_diagnoses": entries,
            "secondary_diagnosis_codes": secondary or [],
        },
        "encounters": [
            {
                "encounter_id": "enc-1",
                "encounter_type": "inpatient",
                "admission_datetime": "2026-06-14T14:23:00",
                "discharge_datetime": "2026-06-24T14:30:00",
                "attending_physician_id": "DR-IM-001",
                "status": "completed",
            }
        ],
        "deceased": False,
    }


def _by_code(conds: list[dict]) -> dict[str, dict]:
    return {c["code"]["coding"][0]["code"]: c for c in conds if c.get("code", {}).get("coding")}


@pytest.mark.parametrize(("country", "aki", "dvt"), [("US", "N17.9", "I82.409"), ("JP", "N17.9", "I82.9")])
def test_conditions_carry_the_complication_onset(country: str, aki: str, dvt: str) -> None:
    entries = complication_diagnosis_entries([_AKI, _DVT], existing_codes=[])
    conds = _by_code(_build_conditions(_record(entries), patient_id="pt-42", country=country))
    assert conds[aki]["onsetDateTime"].startswith("2026-06-20T12:00")
    assert conds[dvt]["onsetDateTime"].startswith("2026-06-18T12:00")
    assert conds[aki]["category"][0]["coding"][0]["code"] == "encounter-diagnosis"


def test_delirium_condition_onset_is_the_complication_onset_not_the_admission() -> None:
    """The dated working entry wins over the undated secondary code."""
    entries = complication_diagnosis_entries([_DELIRIUM], existing_codes=[])
    conds = _by_code(_build_conditions(_record(entries, secondary=["F05"]), patient_id="pt-42", country="US"))
    assert [c for c in conds if c.startswith("F05")] == ["F05"]
    assert conds["F05"]["onsetDateTime"].startswith("2026-06-15T12:00")


# --- guards on the table ---------------------------------------------------

_PROTOCOLS = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "disease" / "reference_data"


def _protocol_complication_tokens() -> set[str]:
    tokens: set[str] = set()
    for f in glob.glob(str(_PROTOCOLS / "*.yaml")):
        data = yaml.safe_load(Path(f).read_text(encoding="utf-8")) or {}
        for entry in data.get("complications") or []:
            if isinstance(entry, dict) and entry.get("name"):
                tokens.add(str(entry["name"]))
    return tokens


def test_every_token_is_a_complication_some_protocol_can_fire() -> None:
    known = _protocol_complication_tokens()
    unknown = sorted(set(complication_diagnosis_codes()) - known)
    assert not unknown, unknown


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_code_resolves_in_both_locales(country: str) -> None:
    system = "icd-10-cm" if country == "US" else "icd-10"
    for token, code in complication_diagnosis_codes().items():
        out = map_diagnosis_code(code, country)
        assert code_exists(system, out, exact=True), (token, code, out)


def test_agrees_with_the_death_cause_chain() -> None:
    from clinosim.modules.document.reference_data_loaders import load_death_cause_chain

    chain = load_death_cause_chain().immediate_cause_complications
    for token, code in complication_diagnosis_codes().items():
        chain_code = chain.get(token)
        if chain_code:
            assert chain_code == code, (token, code, chain_code)


def test_delirium_tokens_resolve_through_the_delirium_rule() -> None:
    for token in delirium_rules().existing_names:
        assert complication_diagnosis_code(token) == "F05"


def test_table_shape() -> None:
    for token, code in complication_diagnosis_codes().items():
        assert re.fullmatch(r"[A-Za-z_]+", token)
        assert re.fullmatch(r"[A-Z]\d{2}(\.\d{1,4})?", code), (token, code)
