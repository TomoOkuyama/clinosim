"""Unit tests for `derive_meta_last_updated` (Issue #549).

Locks the canonical fallback-chain resolver:

- returns the first non-empty value in `prefer` order
- supports dotted paths (e.g. `effectivePeriod.end`) for nested lookups
- returns None when no field yields a value
- treats empty string / None / missing field as "no value"
"""

from __future__ import annotations

from clinosim.modules.output._fhir_common import derive_meta_last_updated


def test_returns_first_non_empty_field() -> None:
    resource = {"authoredOn": "2026-05-01T10:00:00+09:00", "recorded": "2026-04-01T00:00:00+09:00"}
    assert derive_meta_last_updated(resource, ("authoredOn", "recorded")) == "2026-05-01T10:00:00+09:00"


def test_falls_through_empty_string_to_next_field() -> None:
    resource = {"authoredOn": "", "recorded": "2026-04-01T00:00:00+09:00"}
    assert derive_meta_last_updated(resource, ("authoredOn", "recorded")) == "2026-04-01T00:00:00+09:00"


def test_falls_through_missing_key_to_next_field() -> None:
    resource = {"recorded": "2026-04-01T00:00:00+09:00"}
    assert derive_meta_last_updated(resource, ("authoredOn", "recorded")) == "2026-04-01T00:00:00+09:00"


def test_returns_none_when_all_fields_missing_or_empty() -> None:
    resource = {"authoredOn": "", "recorded": None}
    assert derive_meta_last_updated(resource, ("authoredOn", "recorded")) is None


def test_returns_none_for_empty_prefer_tuple() -> None:
    resource = {"date": "2026-01-01"}
    assert derive_meta_last_updated(resource, ()) is None


def test_supports_dotted_nested_path() -> None:
    resource = {
        "effectiveDateTime": "",
        "effectivePeriod": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
    }
    assert derive_meta_last_updated(resource, ("effectiveDateTime", "effectivePeriod.end")) == "2026-01-02T00:00:00Z"


def test_dotted_path_missing_intermediate_returns_none() -> None:
    resource: dict = {"effectiveDateTime": ""}
    assert derive_meta_last_updated(resource, ("effectivePeriod.end",)) is None


def test_dotted_path_intermediate_not_a_dict_returns_none() -> None:
    resource = {"effectivePeriod": "not-a-dict"}
    assert derive_meta_last_updated(resource, ("effectivePeriod.end",)) is None


def test_observation_chain_preserves_pre_migration_order() -> None:
    """Post-migration site 1 (`_fhir_post_process.py`) — Observation walker.

    Locks the order `effectiveDateTime → issued → effectivePeriod.end` so a
    future refactor cannot silently reorder the chain.
    """
    resource = {
        "resourceType": "Observation",
        "issued": "2026-02-01T00:00:00+09:00",
        "effectivePeriod": {"end": "2026-03-01T00:00:00+09:00"},
    }
    assert (
        derive_meta_last_updated(resource, ("effectiveDateTime", "issued", "effectivePeriod.end"))
        == "2026-02-01T00:00:00+09:00"
    )


def test_medication_request_chain_preserves_pre_migration_order() -> None:
    """Post-migration site 2 (`_fhir_post_process.py`) — MedicationRequest branch."""
    resource = {"resourceType": "MedicationRequest", "recorded": "2026-04-01T00:00:00+09:00"}
    assert derive_meta_last_updated(resource, ("authoredOn", "recorded")) == "2026-04-01T00:00:00+09:00"


def test_condition_ai_chain_preserves_pre_migration_order() -> None:
    """Post-migration site 3 (`_fhir_post_process.py`) — Condition / AllergyIntolerance branch."""
    resource = {
        "resourceType": "Condition",
        "assertedDate": "2026-05-01T00:00:00+09:00",
        "onsetDateTime": "2026-06-01T00:00:00+09:00",
    }
    assert (
        derive_meta_last_updated(resource, ("recordedDate", "assertedDate", "onsetDateTime"))
        == "2026-05-01T00:00:00+09:00"
    )
