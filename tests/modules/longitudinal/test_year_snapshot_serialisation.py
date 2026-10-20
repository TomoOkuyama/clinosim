"""YearSnapshot dataclass + CIF-friendly serialisation.

The year-indexed snapshot that `PersonRecord.state_history: list[YearSnapshot]`
holds is written through the CIF writer's `asdict(patient_record)` path
and read back by downstream analysis. Round-trip through json must
preserve every field — year (int), continuous (dict[str, float]),
chronic_stages (dict[str, str]), new_complications (list[str]),
med_additions (list[str]), med_removals (list[str]).

See the Phase 1 plan Task 1 brief + the spec §4.1 for the dataclass
field list.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from clinosim.modules.longitudinal.snapshot import (
    YearSnapshot,
    yearsnapshot_from_dict,
)


@pytest.mark.unit
def test_year_snapshot_default_init_has_empty_dicts_and_lists() -> None:
    """A freshly-constructed snapshot carries empty collections (not
    None) for every optional field so callers can `.get(key, default)`
    and `.append(code)` without pre-checking."""
    snap = YearSnapshot(year=2023)
    assert snap.year == 2023
    assert snap.continuous == {}
    assert snap.chronic_stages == {}
    assert snap.new_complications == []
    assert snap.med_additions == []
    assert snap.med_removals == []


@pytest.mark.unit
def test_year_snapshot_asdict_roundtrips_through_json() -> None:
    """`cif_writer.py` calls `asdict(patient_record)` and
    `json.dump(..., cls=_CIFEncoder)`. The YearSnapshot must survive
    that pipeline byte-for-byte on the fields it carries."""
    snap = YearSnapshot(
        year=2023,
        continuous={"hba1c": 8.3, "ldl": 142.5},
        chronic_stages={"N18": "G3a", "I50": "NYHA II"},
        new_complications=["E11.21"],
        med_additions=["Dapagliflozin"],
        med_removals=["Pioglitazone"],
    )
    d = asdict(snap)
    j = json.dumps(d, sort_keys=True)
    d2 = json.loads(j)
    snap2 = yearsnapshot_from_dict(d2)
    assert snap2 == snap


@pytest.mark.unit
def test_json_round_trip_preserves_year_and_continuous_keys() -> None:
    """Review Focus item 4: CIF JSON round-trip preserves
    `state_history` as a list of dicts and deserialises back to
    `YearSnapshot` instances. Pins the exact field names the
    downstream reader relies on; a rename of `continuous` to
    anything else is a schema break and this test is the regression
    guard."""
    snap = YearSnapshot(year=2024, continuous={"hba1c": 7.3})
    d = asdict(snap)
    assert d["year"] == 2024
    assert d["continuous"] == {"hba1c": 7.3}
    j = json.dumps(d)
    assert '"year": 2024' in j
    assert '"continuous"' in j
    assert '"hba1c"' in j
    snap2 = yearsnapshot_from_dict(json.loads(j))
    assert snap2.year == 2024
    assert snap2.continuous["hba1c"] == 7.3


@pytest.mark.unit
def test_from_dict_tolerates_missing_optional_keys() -> None:
    """Legacy / minimal dicts (e.g. a snapshot written before Phase 2
    adds `new_complications`) must deserialise without raising."""
    snap = yearsnapshot_from_dict({"year": 2022})
    assert snap.year == 2022
    assert snap.continuous == {}
    assert snap.chronic_stages == {}
    assert snap.new_complications == []
    assert snap.med_additions == []
    assert snap.med_removals == []


@pytest.mark.unit
def test_from_dict_requires_year() -> None:
    """`year` is the only mandatory field; without it the snapshot
    has no identity. Deserialising a dict that lacks it is a program
    bug, not a legacy-format case."""
    with pytest.raises(KeyError):
        yearsnapshot_from_dict({"continuous": {}})
