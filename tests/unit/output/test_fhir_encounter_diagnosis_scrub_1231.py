"""Issue #1231: `_scrub_refs_one_pass` also cleans Encounter.diagnosis and reasonReference.

PR #1226 (`_drop_entries_after_death` scrubber pass) covered Composition
section entries, DiagnosticReport.result, MR/SR.basedOn, MA.request
cascade, and DocumentReference.context.related. It missed
``Encounter.diagnosis[*].condition.reference`` (a nested single Reference
inside a BackboneElement list) and ``Encounter.reasonReference[]`` (a
list of Reference).

S105 final audit (JP p=10k / US p=10k) surfaced 6 JP + 1 US dangling
``Encounter → Condition`` refs — the Encounter itself survives the
start-gated after-death allowlist (Issue #1219 / PR #1224), but its
diagnosis[] Condition targets can still drop by ``_dt_fields`` gate
(recordedDate / onsetDateTime > dod). The scrubber now handles both
Encounter reference slots.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4 import _drop_entries_after_death

pytestmark = pytest.mark.unit


def _entry(resource: dict) -> dict:
    return {"resource": resource}


def test_encounter_diagnosis_entry_dropped_when_condition_ref_dangles() -> None:
    """The core fix: Encounter survives after-death gate, but a diagnosis[]
    entry whose Condition ref target is dropped (post-mortem recordedDate)
    is removed from the diagnosis list."""
    condition = {
        "resourceType": "Condition",
        "id": "cond-postmortem",
        "recordedDate": "2025-10-25T10:00:00",  # after dod
    }
    encounter = {
        "resourceType": "Encounter",
        "id": "enc-imp-1",
        "period": {"start": "2025-10-20T08:00:00", "end": "2025-10-27T14:00:00"},
        "diagnosis": [
            {"condition": {"reference": "Condition/cond-postmortem"}, "rank": 1},
            {"condition": {"reference": "Condition/cond-alive"}, "rank": 2},
        ],
    }
    kept_condition = {
        "resourceType": "Condition",
        "id": "cond-alive",
        "recordedDate": "2025-10-21T08:00:00",  # before dod
    }
    kept = _drop_entries_after_death(
        [_entry(condition), _entry(encounter), _entry(kept_condition)],
        "2025-10-22",
    )
    # The post-mortem Condition is dropped.
    assert not any(e["resource"].get("id") == "cond-postmortem" for e in kept)
    # Encounter is kept.
    enc = next(e["resource"] for e in kept if e["resource"]["id"] == "enc-imp-1")
    # Diagnosis[] with dangling ref is scrubbed.
    diag_targets = [d["condition"]["reference"] for d in enc.get("diagnosis", [])]
    assert diag_targets == ["Condition/cond-alive"], f"expected only cond-alive, got {diag_targets}"


def test_encounter_reason_reference_dropped_when_target_dangles() -> None:
    """Same pattern for Encounter.reasonReference[]."""
    condition = {
        "resourceType": "Condition",
        "id": "cond-postmortem",
        "recordedDate": "2025-10-25T10:00:00",
    }
    encounter = {
        "resourceType": "Encounter",
        "id": "enc-imp-2",
        "period": {"start": "2025-10-20T08:00:00", "end": "2025-10-27T14:00:00"},
        "reasonReference": [
            {"reference": "Condition/cond-postmortem"},
            {"reference": "Condition/cond-alive"},
        ],
    }
    kept_condition = {
        "resourceType": "Condition",
        "id": "cond-alive",
        "recordedDate": "2025-10-21T08:00:00",
    }
    kept = _drop_entries_after_death(
        [_entry(condition), _entry(encounter), _entry(kept_condition)],
        "2025-10-22",
    )
    enc = next(e["resource"] for e in kept if e["resource"]["id"] == "enc-imp-2")
    refs = [r["reference"] for r in enc.get("reasonReference", [])]
    assert refs == ["Condition/cond-alive"]


def test_encounter_with_all_diagnosis_dropped_ends_with_empty_list() -> None:
    """Regression guard: an Encounter whose EVERY diagnosis target drops
    keeps an empty diagnosis list (spec-clean, 0..*), not a dangling one."""
    condition = {
        "resourceType": "Condition",
        "id": "cond-postmortem",
        "recordedDate": "2025-10-25T10:00:00",
    }
    encounter = {
        "resourceType": "Encounter",
        "id": "enc-imp-3",
        "period": {"start": "2025-10-20T08:00:00", "end": "2025-10-27T14:00:00"},
        "diagnosis": [{"condition": {"reference": "Condition/cond-postmortem"}, "rank": 1}],
    }
    kept = _drop_entries_after_death([_entry(condition), _entry(encounter)], "2025-10-22")
    enc = next(e["resource"] for e in kept if e["resource"]["id"] == "enc-imp-3")
    assert enc.get("diagnosis") == []


def test_encounter_no_diagnosis_field_unchanged() -> None:
    """Encounter without diagnosis / reasonReference passes through untouched."""
    encounter = {
        "resourceType": "Encounter",
        "id": "enc-plain",
        "period": {"start": "2025-10-20", "end": "2025-10-27"},
    }
    kept = _drop_entries_after_death([_entry(encounter)], "2025-10-22")
    assert len(kept) == 1
    assert kept[0]["resource"] == encounter
