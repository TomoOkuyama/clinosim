"""The validator bridges validate a document Composition inside its document
Bundle (Issue #3147): the Composition first, then every resource it
references, directly or through those resources."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("fhir_document_bundle", _ROOT / "scripts" / "fhir_document_bundle.py")
assert _spec and _spec.loader
fdb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fdb)


def _resources() -> dict[str, dict]:
    rs = [
        {
            "resourceType": "Composition",
            "id": "c1",
            "meta": {"profile": ["http://example.org/P"]},
            "subject": {"reference": "Patient/p1"},
            "section": [{"entry": [{"reference": "Organization/o1"}, {"reference": "Condition/x1"}]}],
        },
        {"resourceType": "Patient", "id": "p1", "managingOrganization": {"reference": "Organization/o2"}},
        {"resourceType": "Organization", "id": "o1"},
        {"resourceType": "Organization", "id": "o2"},
        {"resourceType": "Condition", "id": "x1", "subject": {"reference": "Patient/p1"}},
        {"resourceType": "Observation", "id": "unrelated"},
    ]
    return {f"{r['resourceType']}/{r['id']}": r for r in rs}


def test_the_bundle_holds_the_composition_first_and_every_referenced_resource() -> None:
    index = _resources()
    bundle = fdb.document_bundle(index["Composition/c1"], index)
    assert bundle["resourceType"] == "Bundle" and bundle["type"] == "document"
    keys = [f"{e['resource']['resourceType']}/{e['resource']['id']}" for e in bundle["entry"]]
    assert keys[0] == "Composition/c1"
    assert sorted(keys[1:]) == ["Condition/x1", "Organization/o1", "Organization/o2", "Patient/p1"]
    for e in bundle["entry"]:
        r = e["resource"]
        assert e["fullUrl"].endswith(f"/{r['resourceType']}/{r['id']}")
    assert bundle["identifier"]["value"] and bundle["timestamp"]


def test_a_reference_missing_from_the_cohort_is_reported() -> None:
    index = _resources()
    del index["Organization/o1"]
    bundle = fdb.document_bundle(index["Composition/c1"], index)
    assert fdb.missing_references(bundle) == ["Organization/o1"]


def test_the_declared_profile_is_read_from_the_composition() -> None:
    index = _resources()
    assert fdb.declares_profile(fdb.document_bundle(index["Composition/c1"], index), "http://example.org/P")


def test_the_jp_bridge_validates_compositions_as_document_bundles() -> None:
    text = (_ROOT / "scripts" / "validate_jp.sh").read_text()
    assert "fhir_document_bundle.py" in text
    assert "declares_profile" in text
