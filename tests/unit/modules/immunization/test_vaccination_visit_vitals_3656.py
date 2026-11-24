"""A vaccination visit has a length and its pre-vaccination vitals reference it (Issue #3656)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.immunization.enricher import _synthesize_vaccination_encounter, vaccination_visit_minutes
from clinosim.modules.output.fhir_r4.lib.ed_reattribution import vital_sign_encounter_id
from clinosim.types.encounter import ImmunizationRecord

pytestmark = pytest.mark.unit

_PRIMARY = "ENC-POP-000001-AAA"
_VAX = "ENC-VAX-POP-000001-bbb"


def _ctx(vital_ts: list) -> SimpleNamespace:
    record = {
        "encounters": [
            {
                "encounter_id": _PRIMARY,
                "encounter_type": "emergency",
                "admission_datetime": datetime(2026, 1, 7, 21, 54),
                "discharge_datetime": datetime(2026, 1, 8, 8, 30),
            },
            {
                "encounter_id": _VAX,
                "encounter_type": "outpatient",
                "admission_datetime": datetime(2026, 11, 2, 10, 0),
                "discharge_datetime": datetime(2026, 11, 2, 10, 15),
            },
        ],
        "vital_signs": [{"timestamp": ts, "data_source": "manual"} for ts in vital_ts],
    }
    return SimpleNamespace(record=record, primary_enc_id=_PRIMARY)


def test_synthesized_visit_has_a_length() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 11, 2))
    enc = _synthesize_vaccination_encounter(imm, "POP-000001", "US")
    assert (enc.discharge_datetime - enc.admission_datetime).total_seconds() == vaccination_visit_minutes() * 60
    assert vaccination_visit_minutes() > 0


def test_vital_set_inside_the_vaccination_visit_references_it() -> None:
    ctx = _ctx([datetime(2026, 11, 2, 10, 0, 30), "2026-11-02T10:00:00"])
    assert [vital_sign_encounter_id(vs, ctx) for vs in ctx.record["vital_signs"]] == [_VAX, _VAX]


def test_vital_set_outside_every_other_visit_keeps_the_primary() -> None:
    ctx = _ctx([datetime(2026, 1, 7, 22, 0), datetime(2026, 11, 2, 11, 0)])
    assert [vital_sign_encounter_id(vs, ctx) for vs in ctx.record["vital_signs"]] == [_PRIMARY, _PRIMARY]
