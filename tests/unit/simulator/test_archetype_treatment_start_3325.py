"""Issue #3325: archetype treatment starts listed under ``all`` (every country)
are applied, and a start block keyed by anything other than a country slot or
``all`` fails disease-protocol validation instead of silently starting
nothing."""

from __future__ import annotations

import copy
import logging

import pytest

from clinosim.codes.drugs import drug_classes
from clinosim.modules.disease.localization import archetype_start_entries
from clinosim.modules.disease.protocol import DiseaseProtocol, load_disease_protocol

pytestmark = pytest.mark.unit

_NE = {"drug_id": "norepinephrine", "dose": "0.1 ug/kg/min IV drip"}
_MICA = {"drug_id": "micafungin", "dose": "100mg IV daily"}


def test_all_key_applies_to_every_country() -> None:
    for country in ("US", "JP"):
        assert archetype_start_entries({"start": {"all": [_NE]}}, country) == [_NE]


def test_country_entries_are_added_to_all() -> None:
    mod = {"start": {"all": [_NE], "japan": [_MICA]}}
    assert archetype_start_entries(mod, "JP") == [_NE, _MICA]
    assert archetype_start_entries(mod, "US") == [_NE]


def test_no_start_block_starts_nothing() -> None:
    assert archetype_start_entries({"action": "icu_transfer"}, "US") == []


def test_unknown_start_key_fails_validation() -> None:
    # A deep copy: the cached protocol is shared.
    data = copy.deepcopy(load_disease_protocol("sepsis").model_dump())
    data["course_archetypes"]["dip_then_recovery"]["treatment_modifications"]["day_2"]["start"] = {"everyone": [_NE]}
    with pytest.raises(ValueError, match="everyone"):
        DiseaseProtocol.model_validate(data)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_septic_shock_archetype_starts_norepinephrine_on_day_0(country: str) -> None:
    from clinosim.simulator import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    logging.disable(logging.WARNING)
    try:
        ds = run_forced(
            ForcedScenario(disease_id="sepsis", count=1, severity="severe", archetype="sudden_deterioration"),
            SimulatorConfig(random_seed=23, country=country),
        )
    finally:
        logging.disable(logging.NOTSET)
    record = ds.patients[0]
    admission = record.encounters[0].admission_datetime
    starts = [o for o in record.orders if o.drug_id == "norepinephrine" and "-START-D0-" in o.order_id]
    assert starts, "norepinephrine is not ordered on the shock day"
    given = [
        m
        for m in record.medication_administrations
        if m.status == "given" and "vasopressor" in drug_classes(m.drug_id or m.drug_name)
    ]
    assert given and min((m.actual_datetime or m.scheduled_datetime) for m in given).date() == admission.date()
