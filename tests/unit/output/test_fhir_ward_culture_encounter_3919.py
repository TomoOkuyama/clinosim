"""Issue #3919: a culture belongs to the Encounter of its collection time.

The microbiology builder shared one ``encounter`` Reference dict between all
cultures of a record; the ED routing then rewrote it in place for the ED
culture and every ward culture followed it to the ED Encounter.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id
from clinosim.modules.output.fhir_r4.labs.microbiology import _bb_microbiology
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.ed_reattribution import reattribute_ed_phase_by_time

pytestmark = pytest.mark.unit

_IMP = "ENC-POP-000001-111"
_IMP_REF = f"Encounter/{resolve_encounter_id(_IMP)}"
_ED_REF = f"Encounter/{resolve_encounter_id(f'{_IMP}-ED')}"


def _culture(collected: str, specimen: str = "blood") -> dict:
    return {
        "encounter_id": _IMP,
        "specimen": specimen,
        "test_loinc": "600-7",
        "collected_datetime": collected,
        "reported_datetime": "2026-02-21T09:00:00",
        "growth": True,
        "organism_snomed": "3092008",
        "susceptibilities": [{"antibiotic_loinc": "19000-9", "interpretation": "S"}],
    }


def _routed(cultures: list[dict]) -> list[dict]:
    record = {
        "encounters": [
            {
                "encounter_id": _IMP,
                "admit_source": "emd",
                "admission_datetime": "2026-02-16T10:20:00",
                "discharge_datetime": "2026-02-25T10:00:00",
            }
        ],
        "orders": [],
        "microbiology": cultures,
    }
    ctx = BundleContext(
        record=record,
        country="US",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id=_IMP,
        patient_sex="M",
    )
    out = _bb_microbiology(ctx)
    for resource in out:  # the builder loop routes each resource right after it is built
        reattribute_ed_phase_by_time(resource, ctx)
    return out


def _result_refs(out: list[dict]) -> dict[str, set[str]]:
    """collection time -> Encounter references of its Observations and DiagnosticReport."""
    spec_time = {r["id"]: r["collection"]["collectedDateTime"] for r in out if r["resourceType"] == "Specimen"}
    refs: dict[str, set[str]] = {}
    for r in out:
        if r["resourceType"] == "Specimen":
            continue
        t = spec_time[
            (r.get("specimen") if isinstance(r.get("specimen"), dict) else r["specimen"][0])["reference"].split("/")[1]
        ]
        refs.setdefault(t, set()).add(r["encounter"]["reference"])
    return refs


def test_ward_culture_after_an_ed_culture_stays_on_the_inpatient_encounter() -> None:
    # ED culture first (in the 4-hour window before the 10:20 admission), ward culture on day 5.
    out = _routed([_culture("2026-02-16T07:30:00", "sputum"), _culture("2026-02-21T20:20:00")])
    refs = _result_refs(out)
    assert refs["2026-02-16T07:30:00"] == {_ED_REF}
    assert refs["2026-02-21T20:20:00"] == {_IMP_REF}


def test_every_ward_culture_is_inpatient_even_when_the_ed_culture_is_in_the_middle() -> None:
    out = _routed(
        [_culture("2026-02-18T08:00:00"), _culture("2026-02-16T07:30:00", "sputum"), _culture("2026-02-21T20:20:00")]
    )
    refs = _result_refs(out)
    assert refs["2026-02-16T07:30:00"] == {_ED_REF}
    assert refs["2026-02-18T08:00:00"] == {_IMP_REF}
    assert refs["2026-02-21T20:20:00"] == {_IMP_REF}
