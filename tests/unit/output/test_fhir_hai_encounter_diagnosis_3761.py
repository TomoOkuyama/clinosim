"""Issue #3761: an HAI Condition is referenced from its Encounter's diagnosis."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.conditions.hai import _bb_hai_conditions
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_conditions, _bb_encounters
from tests.unit.output.test_fhir_encounter_diagnosis_refs_3597 import SEPSIS_DX, _ctx

HAI = {
    "icd10_code": "T80.211A",
    "snomed_code": "434656007",
    "hai_id": "hai-ENC-1-clabsi-0",
    "encounter_id": "ENC-1",
    "onset_date": "2026-05-15",
}


def _with_hai(country: str, hais: list[dict]):
    ctx = _ctx(country, dx=SEPSIS_DX, chronic=[{"code": "I10"}])
    ctx.record["extensions"] = {"hai": hais}
    return ctx


@pytest.mark.parametrize("country", ["US", "JP"])
def test_hai_condition_is_listed_as_a_complication_after_the_other_diagnoses(country: str) -> None:
    ctx = _with_hai(country, [HAI])
    (enc,) = [r for r in _bb_encounters(ctx) if r["resourceType"] == "Encounter"]
    (hai_cond,) = _bb_hai_conditions(ctx)
    diag = enc["diagnosis"]
    assert diag[-1]["condition"]["reference"] == f"Condition/{hai_cond['id']}"
    assert diag[-1]["use"]["coding"][0]["code"] == "CM"
    assert [d["rank"] for d in diag] == list(range(1, len(diag) + 1))
    refs = [d["condition"]["reference"] for d in diag]
    assert len(refs) == len(set(refs))
    # Every encounter-diagnosis Condition of the record (HAI included) is referenced.
    all_conds = [*_bb_conditions(ctx), *_bb_hai_conditions(ctx)]
    dx_ids = {
        c["id"]
        for c in all_conds
        if any(x["code"] == "encounter-diagnosis" for cat in c["category"] for x in cat["coding"])
    }
    assert dx_ids <= {r.split("/")[-1] for r in refs}


def test_two_hai_events_are_ranked_in_emission_order() -> None:
    second = {**HAI, "hai_id": "hai-ENC-1-cauti-1", "icd10_code": "T83.511A"}
    ctx = _with_hai("US", [HAI, second])
    (enc,) = [r for r in _bb_encounters(ctx) if r["resourceType"] == "Encounter"]
    assert [d["condition"]["reference"] for d in enc["diagnosis"][-2:]] == [
        "Condition/hai-ENC-1-clabsi-0",
        "Condition/hai-ENC-1-cauti-1",
    ]


def test_an_hai_without_a_condition_is_not_referenced() -> None:
    ctx = _with_hai("US", [{**HAI, "icd10_code": ""}])
    (enc,) = [r for r in _bb_encounters(ctx) if r["resourceType"] == "Encounter"]
    assert not _bb_hai_conditions(ctx)
    assert all("hai-" not in d["condition"]["reference"] for d in enc["diagnosis"])
