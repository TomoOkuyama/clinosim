"""Issue #1218: `_drop_entries_after_death` must scrub dangling refs on survivors.

The Issue #926 death-filter drops event resources (Observation, MA,
Procedure, DiagnosticReport, DocumentReference, ClinicalImpression)
whose dateTime is after `date_of_death` from the bundle. Before this
fix, references to those dropped ids on surviving parent resources
(`Composition.section.entry[]`, `DiagnosticReport.result[]`,
`Observation.hasMember/derivedFrom[]`, MedicationAdministration.request
cascade, etc.) were left dangling.

P=10000 s=1111 audit: 1,866 dangling
`Composition.section.entry -> Observation/…` references (vs / news2 /
lab / gcs Observations recorded up until the discharge that survived,
dropped because effectiveDateTime > dod, while the enclosing
Composition's `.date` was ≤ dod and survived intact).

Fix: mirror the `_drop_entries_after_snapshot` scrubber pattern on the
after-death filter — same helper (`_scrub_refs_one_pass`), same
3-pass fixed-point bound.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4 import _drop_entries_after_death

pytestmark = pytest.mark.unit


def _entry(resource: dict) -> dict:
    return {"resource": resource}


def test_composition_entry_ref_scrubbed_when_observation_dropped() -> None:
    """The core case: an Observation dropped post-mortem must not remain
    referenced by a surviving Composition."""
    dod = "2025-10-22"
    composition = {
        "resourceType": "Composition",
        "id": "comp-1",
        "date": "2025-10-20T10:00:00",  # before dod → survives
        "section": [
            {
                "title": "所見",
                "entry": [
                    {"reference": "Observation/obs-post-mortem-1"},
                    {"reference": "Observation/obs-pre-mortem-2"},
                ],
            }
        ],
    }
    pre_mortem_obs = {
        "resourceType": "Observation",
        "id": "obs-pre-mortem-2",
        "status": "final",
        "effectiveDateTime": "2025-10-20T09:30:00",
        "code": {"text": "HR"},
    }
    post_mortem_obs = {
        "resourceType": "Observation",
        "id": "obs-post-mortem-1",
        "status": "final",
        "effectiveDateTime": "2025-10-24T10:00:00",  # after dod → dropped
        "code": {"text": "HR"},
    }
    kept = _drop_entries_after_death([_entry(composition), _entry(pre_mortem_obs), _entry(post_mortem_obs)], dod)
    resources = [e["resource"] for e in kept]
    ids = [r["id"] for r in resources]
    assert "comp-1" in ids
    assert "obs-pre-mortem-2" in ids
    assert "obs-post-mortem-1" not in ids  # dropped
    comp = next(r for r in resources if r["id"] == "comp-1")
    refs = [e["reference"] for e in comp["section"][0]["entry"]]
    assert "Observation/obs-post-mortem-1" not in refs, "dangling ref must be scrubbed"
    assert "Observation/obs-pre-mortem-2" in refs, "living ref must survive"


def test_diagnostic_report_result_ref_scrubbed_when_observation_dropped() -> None:
    dod = "2025-10-22"
    dr = {
        "resourceType": "DiagnosticReport",
        "id": "dr-1",
        "issued": "2025-10-20T10:00:00",
        "result": [
            {"reference": "Observation/obs-post-mortem-x"},
            {"reference": "Observation/obs-alive-y"},
        ],
    }
    obs_alive = {
        "resourceType": "Observation",
        "id": "obs-alive-y",
        "effectiveDateTime": "2025-10-20T09:00:00",
        "code": {"text": "WBC"},
    }
    obs_dead = {
        "resourceType": "Observation",
        "id": "obs-post-mortem-x",
        "effectiveDateTime": "2025-10-24T10:00:00",
        "code": {"text": "WBC"},
    }
    kept = _drop_entries_after_death([_entry(dr), _entry(obs_alive), _entry(obs_dead)], dod)
    dr_survived = next(r for r in (e["resource"] for e in kept) if r["id"] == "dr-1")
    refs = [e["reference"] for e in dr_survived.get("result", [])]
    assert "Observation/obs-post-mortem-x" not in refs
    assert "Observation/obs-alive-y" in refs


def test_medadmin_dropped_cascade_scrubs_from_composition() -> None:
    """MA dropped because its own effectivePeriod.start > dod; a Composition
    that referenced it must have that ref removed."""
    dod = "2025-10-22"
    composition = {
        "resourceType": "Composition",
        "id": "comp-plan",
        "date": "2025-10-21T09:00:00",
        "section": [
            {
                "title": "計画",
                "entry": [{"reference": "MedicationAdministration/ma-post-mortem"}],
            }
        ],
    }
    ma = {
        "resourceType": "MedicationAdministration",
        "id": "ma-post-mortem",
        "effectivePeriod": {"start": "2025-10-24T08:00:00"},
    }
    kept = _drop_entries_after_death([_entry(composition), _entry(ma)], dod)
    comp = next(r for r in (e["resource"] for e in kept) if r["id"] == "comp-plan")
    refs = [e["reference"] for e in comp["section"][0]["entry"]]
    assert "MedicationAdministration/ma-post-mortem" not in refs


def test_no_scrubbing_when_nothing_dropped() -> None:
    """Regression guard: if no entries are dropped, references are untouched."""
    dod = "2026-12-31"
    composition = {
        "resourceType": "Composition",
        "id": "comp-1",
        "date": "2025-10-20T10:00:00",
        "section": [
            {
                "title": "所見",
                "entry": [{"reference": "Observation/obs-1"}],
            }
        ],
    }
    obs = {
        "resourceType": "Observation",
        "id": "obs-1",
        "effectiveDateTime": "2025-10-20T09:30:00",
        "code": {"text": "HR"},
    }
    kept = _drop_entries_after_death([_entry(composition), _entry(obs)], dod)
    comp = next(r for r in (e["resource"] for e in kept) if r["id"] == "comp-1")
    refs = [e["reference"] for e in comp["section"][0]["entry"]]
    assert refs == ["Observation/obs-1"]


def test_scrubber_shape_matches_after_snapshot_pattern() -> None:
    """Assert the after-death filter uses the same scrubber helper as the
    after-snapshot filter, so a future addition to `_scrub_refs_one_pass`
    (e.g. widening to single-ref fields) benefits both filters uniformly.
    """
    import inspect

    from clinosim.modules.output.fhir_r4 import _drop_entries_after_death as fn

    src = inspect.getsource(fn)
    assert "_scrub_refs_one_pass" in src, (
        "after-death filter must reuse `_scrub_refs_one_pass` so scrubber extensions propagate to both drop paths"
    )
