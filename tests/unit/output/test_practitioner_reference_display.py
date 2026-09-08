"""Practitioner Reference.display population — Issue #1178.

Before this walker, every `{"reference": "Practitioner/…"}` in every
resource type (Composition.author, ClinicalImpression.assessor,
DiagnosticReport.performer, DocumentReference.author, Condition.
asserter, CareTeam.participant[].member) omitted `display` — 100%
missing across 171,781 references in the JP p=10000 sample.

The post-process walker resolves each reference against the shared
roster map and populates `Reference.display` in place.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.post_process.populate import (
    _populate_practitioner_reference_display,
    _resolve_practitioner_display,
)

_ROSTER = {
    "DR-IM-005": {"name": "比嘉 進", "role": "physician"},
    "DR-CA-002": {"name": "加瀬 幸男", "role": "physician"},
    "TECH-LAB-001": {"name": "山田 花子", "role": "medical_technologist"},
}


def test_resolve_display_returns_name_when_staff_in_roster() -> None:
    assert _resolve_practitioner_display("DR-IM-005", _ROSTER) == "比嘉 進"


def test_resolve_display_returns_empty_when_staff_missing() -> None:
    assert _resolve_practitioner_display("DR-UNKNOWN", _ROSTER) == ""


def test_resolve_display_empty_roster_returns_empty() -> None:
    assert _resolve_practitioner_display("DR-IM-005", None) == ""
    assert _resolve_practitioner_display("DR-IM-005", {}) == ""


def test_walker_fills_composition_author_display() -> None:
    resource = {
        "resourceType": "Composition",
        "author": [{"reference": "Practitioner/DR-IM-005"}],
    }
    _populate_practitioner_reference_display(resource, _ROSTER)
    assert resource["author"][0]["display"] == "比嘉 進"


def test_walker_fills_diagnostic_report_performer_display() -> None:
    resource = {
        "resourceType": "DiagnosticReport",
        "performer": [{"reference": "Practitioner/TECH-LAB-001"}],
    }
    _populate_practitioner_reference_display(resource, _ROSTER)
    assert resource["performer"][0]["display"] == "山田 花子"


def test_walker_fills_condition_asserter_display() -> None:
    resource = {
        "resourceType": "Condition",
        "asserter": {"reference": "Practitioner/DR-CA-002"},
    }
    _populate_practitioner_reference_display(resource, _ROSTER)
    assert resource["asserter"]["display"] == "加瀬 幸男"


def test_walker_fills_nested_careteam_participant_member() -> None:
    resource = {
        "resourceType": "CareTeam",
        "participant": [
            {"role": [{"text": "primary"}], "member": {"reference": "Practitioner/DR-IM-005"}},
        ],
    }
    _populate_practitioner_reference_display(resource, _ROSTER)
    assert resource["participant"][0]["member"]["display"] == "比嘉 進"


def test_walker_skips_non_practitioner_references() -> None:
    # Patient / Organization references must not be touched.
    resource = {
        "subject": {"reference": "Patient/pt-abc"},
        "managingOrganization": {"reference": "Organization/org-1"},
    }
    _populate_practitioner_reference_display(resource, _ROSTER)
    assert "display" not in resource["subject"]
    assert "display" not in resource["managingOrganization"]


def test_walker_idempotent_when_display_already_present() -> None:
    # A pre-existing display must not be overwritten (idempotent).
    resource = {
        "author": [{"reference": "Practitioner/DR-IM-005", "display": "pre-existing"}],
    }
    _populate_practitioner_reference_display(resource, _ROSTER)
    assert resource["author"][0]["display"] == "pre-existing"


def test_walker_skips_when_staff_not_in_roster() -> None:
    # Never fabricate — silence is the correct outcome.
    resource = {
        "author": [{"reference": "Practitioner/DR-ORPHAN"}],
    }
    _populate_practitioner_reference_display(resource, _ROSTER)
    assert "display" not in resource["author"][0]


def test_walker_empty_roster_is_noop() -> None:
    resource = {
        "author": [{"reference": "Practitioner/DR-IM-005"}],
    }
    _populate_practitioner_reference_display(resource, None)
    assert "display" not in resource["author"][0]
