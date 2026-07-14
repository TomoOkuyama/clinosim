"""Unit tests for clinosim.audit.axes.clinical per-organism helpers
(PR3b-3 chain completion D1 + D2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes import clinical
from clinosim.audit.types import Cohort


def _write(path: Path, country: str, file: str, rows: list[dict]) -> None:
    p = path / country / "fhir_r4" / file
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _mb_org(enc: str, idx: int, organism_snomed: str | None) -> dict:
    """mb-org-* Observation, SNOMED organism or no-growth."""
    obs: dict = {
        "resourceType": "Observation",
        "id": f"mb-org-{enc}-{idx}",
        "encounter": {"reference": f"Encounter/{enc}"},
        "code": {"coding": [{"code": "600-7"}]},
    }
    if organism_snomed:
        obs["valueCodeableConcept"] = {
            "coding": [{"system": "http://snomed.info/sct", "code": organism_snomed}]
        }
    else:
        obs["valueString"] = "No growth"
    return obs


@pytest.mark.unit
def test_organism_per_encounter_basic(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org("E1", 0, "3092008"),       # S.aureus
        _mb_org("E2", 0, "112283007"),     # E.coli
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {"E1": {"3092008"}, "E2": {"112283007"}}


@pytest.mark.unit
def test_organism_per_encounter_multiple_organisms_same_encounter(tmp_path: Path) -> None:
    """A CLABSI encounter with both S.aureus + S.epidermidis blood cultures."""
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org("E1", 0, "3092008"),       # S.aureus
        _mb_org("E1", 1, "11638008"),      # S.epidermidis
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {"E1": {"3092008", "11638008"}}


@pytest.mark.unit
def test_organism_per_encounter_skips_no_growth(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org("E1", 0, None),            # no-growth → valueString
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_encounter_skips_non_mb_observations(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "lab-E1-0001",  # NOT mb-org-*
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "6690-2"}]},
            "valueQuantity": {"value": 14000},
        },
        {
            "resourceType": "Observation",
            "id": "vs-E1-0001",   # vital signs, also NOT mb-org-*
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "8867-4"}]},
            "valueQuantity": {"value": 88},
        },
        _mb_org("E1", 0, "3092008"),
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {"E1": {"3092008"}}


@pytest.mark.unit
def test_organism_per_encounter_skips_missing_encounter_ref(tmp_path: Path) -> None:
    """A mb-org-* without encounter ref must be skipped (no enc_id key)."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-orphan-0",
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}]
            },
        },
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_encounter_empty_observation_file(tmp_path: Path) -> None:
    """No Observation.ndjson at all → empty dict, no crash."""
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_encounter_skips_non_snomed_coding(tmp_path: Path) -> None:
    """A mb-org-* whose valueCodeableConcept uses non-SNOMED system is skipped."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://loinc.org", "code": "12345-6"}],
            },
        },
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_panel_eligible_organisms_includes_antibiogram_keys() -> None:
    """All organisms in hai_antibiogram.yaml appear in the per-hai_type set.

    PR3b-3 stage-1 adversarial finding I4 fix: previously this test imported
    `load_hai_antibiogram` and asserted equality against the helper, which
    used the same loader — a bug swapping nested levels in either side
    would still pass. Now compares against a HARD-CODED expected set that
    must be updated in lockstep with hai_antibiogram.yaml. A nesting-swap
    bug (e.g. helper returning {hai_type: {antibiotic: organism}} instead
    of {hai_type: {organism: ...}}) would now FAIL.
    """
    out = clinical._panel_eligible_organisms()
    # Hard-coded expected — must match hai_antibiogram.yaml top-level shape
    # {hai_type: {organism_snomed: {antibiotic_key: [S, I, R]}}}. Adding an
    # organism to the YAML requires updating this set too; the lockstep
    # forces both sides to be deliberate.
    expected = {
        "clabsi": {
            "3092008",    # S.aureus
            "60875001",   # CoNS (Coagulase-negative Staphylococci)
            "112283007",  # E.coli
            "56415008",   # K.pneumoniae
            "52499004",   # P.aeruginosa
        },
        "cauti": {
            "112283007",  # E.coli
            "56415008",   # K.pneumoniae
            "52499004",   # P.aeruginosa
            "73457008",   # P.mirabilis
        },
        "vap": {
            "3092008",    # S.aureus
            "52499004",   # P.aeruginosa
            "56415008",   # K.pneumoniae
            "112283007",  # E.coli
            "14385002",   # Enterobacter
            "91288006",   # A.baumannii
            "113697002",  # S.maltophilia
        },
    }
    assert out == expected, (
        f"panel_eligible_organisms diverged from expected lockstep set; "
        f"got {out!r}, expected {expected!r}. If hai_antibiogram.yaml was "
        f"intentionally extended, update the expected set here in lockstep."
    )


@pytest.mark.unit
def test_panel_eligible_organisms_excludes_no_panel_organisms() -> None:
    """E.faecalis 78065002 + C.albicans 53326005 are not in any
    panel-eligible set (no antibiogram entry → auto-excluded)."""
    out = clinical._panel_eligible_organisms()
    for hai_type, orgs in out.items():
        assert "78065002" not in orgs, (
            f"{hai_type}: E.faecalis 78065002 leaked into panel-eligible set"
        )
        assert "53326005" not in orgs, (
            f"{hai_type}: C.albicans 53326005 leaked into panel-eligible set"
        )


@pytest.mark.unit
def test_panel_eligible_organisms_returns_known_hai_types() -> None:
    """Smoke: every HAI_TYPES constant entry has at least one panel-eligible org."""
    from clinosim.modules.hai import HAI_TYPES

    out = clinical._panel_eligible_organisms()
    for hai_type in HAI_TYPES:
        assert hai_type in out
        assert out[hai_type], f"{hai_type}: empty panel-eligible set"


# ----------------------------------------------------------------------------
# PR3b-3 stage-1 adversarial fixes (PR #112 post-merge fan-out)
# ----------------------------------------------------------------------------


@pytest.mark.unit
def test_organism_per_encounter_uses_canonical_snomed_uri_not_substring(tmp_path: Path) -> None:
    """C3 fix: substring `"snomed" in sys_uri` matched bogus URIs like
    `"http://example.com/has-snomed-prefix"`. Canonical equality must reject
    any URI other than the official SNOMED CT URI."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{
                    "system": "http://example.com/has-snomed-prefix",
                    "code": "3092008",
                }],
            },
        },
        {
            "resourceType": "Observation",
            "id": "mb-org-E2-0",
            "encounter": {"reference": "Encounter/E2"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{
                    "system": "urn:oid:2.16.840.1.113883.6.96",  # OID form of SNOMED CT
                    "code": "3092008",
                }],
            },
        },
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    # Both should be excluded under canonical-equality semantics. The OID
    # form is also legit SNOMED but we choose the URL canonical (matches the
    # FHIR builder + codes/loader.get_system_uri("snomed-ct")). If we ever
    # need the OID form, add it to a canonical set with deliberate intent
    # rather than accept it implicitly via substring match.
    assert out == {}, f"non-canonical SNOMED URIs must be excluded; got {out}"


@pytest.mark.unit
def test_organism_per_encounter_accepts_canonical_snomed_uri_only(tmp_path: Path) -> None:
    """C3 fix: only `http://snomed.info/sct` (the canonical URL) is accepted."""
    from clinosim.codes import get_system_uri

    canonical = get_system_uri("snomed-ct")
    assert canonical == "http://snomed.info/sct"

    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": canonical, "code": "3092008"}],
            },
        },
    ])
    out = clinical._organism_per_encounter(Cohort.open(tmp_path), "us")
    assert out == {"E1": {"3092008"}}


@pytest.mark.unit
def test_mb_org_id_prefix_canonical_constant() -> None:
    """C4 fix: the mb-org id prefix is now a shared canonical constant
    imported by both the FHIR builder (writer) and the audit helper
    (reader). Pins the contract so a rename in either side raises an
    ImportError at module load instead of silently no-op'ing the gate."""
    from clinosim.modules.output._fhir_microbiology import MB_ORG_ID_PREFIX

    assert MB_ORG_ID_PREFIX == "mb-org-"
    # The audit helper must import the same constant — proving they're
    # coupled and a future rename in _fhir_microbiology.py will trigger
    # an import-time NameError in clinical.py, not a silent no-op.
    import clinosim.audit.axes.clinical as _mod
    assert _mod.MB_ORG_ID_PREFIX is MB_ORG_ID_PREFIX


# ----------------------------------------------------------------------------
# PR3b-5 specimen-based helpers
# ----------------------------------------------------------------------------


def _mb_org_with_specimen(
    enc: str, idx: int, organism_snomed: str | None,
    spec_id: str | None = None, hai_event_id: str = "",
) -> dict:
    """mb-org-* Observation with explicit specimen reference + optional HAI
    identifier. PR3b-5 helpers join susc → specimen → organism so the
    specimen ref is the load-bearing field, not the encounter ref."""
    obs: dict = {
        "resourceType": "Observation",
        "id": f"mb-org-{enc}-{idx}",
        "encounter": {"reference": f"Encounter/{enc}"},
        "code": {"coding": [{"code": "600-7"}]},
    }
    if spec_id is not None:
        obs["specimen"] = {"reference": f"Specimen/{spec_id}"}
    if organism_snomed:
        obs["valueCodeableConcept"] = {
            "coding": [{"system": "http://snomed.info/sct", "code": organism_snomed}]
        }
    else:
        obs["valueString"] = "No growth"
    if hai_event_id:
        from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM
        obs["identifier"] = [{"system": HAI_EVENT_ID_SYSTEM, "value": hai_event_id}]
    return obs


@pytest.mark.unit
def test_organism_per_specimen_basic(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org_with_specimen("E1", 0, "3092008", spec_id="spec-E1-0"),
        _mb_org_with_specimen("E2", 0, "112283007", spec_id="spec-E2-0"),
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {"spec-E1-0": "3092008", "spec-E2-0": "112283007"}


@pytest.mark.unit
def test_organism_per_specimen_multi_specimen_same_encounter(tmp_path: Path) -> None:
    """C1 resolution precondition: an encounter with 2 specimens (S.aureus +
    S.epidermidis) → 2 distinct specimen_id → organism mappings, not 1
    encounter → organism set. This is the load-bearing difference from
    _organism_per_encounter."""
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org_with_specimen("E1", 0, "3092008",  spec_id="spec-E1-0"),
        _mb_org_with_specimen("E1", 1, "60875001", spec_id="spec-E1-1"),
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {"spec-E1-0": "3092008", "spec-E1-1": "60875001"}


@pytest.mark.unit
def test_organism_per_specimen_skips_no_growth(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org_with_specimen("E1", 0, None, spec_id="spec-E1-0"),
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_specimen_skips_missing_specimen_ref(tmp_path: Path) -> None:
    """mb-org-* without specimen reference cannot be joined → skip."""
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org_with_specimen("E1", 0, "3092008", spec_id=None),
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_specimen_skips_non_canonical_snomed(tmp_path: Path) -> None:
    """Canonical SNOMED URI equality from PR #113 C3 fix: non-canonical
    system URIs are rejected, not substring-matched."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "specimen": {"reference": "Specimen/spec-E1-0"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "urn:oid:2.16.840.1.113883.6.96",
                            "code": "3092008"}],
            },
        },
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_specimen_skips_non_mb_observations(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "lab-E1-0001",
            "specimen": {"reference": "Specimen/spec-E1-X"},
            "encounter": {"reference": "Encounter/E1"},
            "code": {"coding": [{"code": "6690-2"}]},
            "valueQuantity": {"value": 14000},
        },
    ])
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_organism_per_specimen_empty_file(tmp_path: Path) -> None:
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    out = clinical._organism_per_specimen(Cohort.open(tmp_path), "us")
    assert out == {}


@pytest.mark.unit
def test_hai_specimens_includes_hai_identifier(tmp_path: Path) -> None:
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_org_with_specimen("E1", 0, "3092008",
                              spec_id="spec-E1-0",
                              hai_event_id="hai-clabsi-1"),
        _mb_org_with_specimen("E2", 0, "112283007",
                              spec_id="spec-E2-0"),  # community, no identifier
    ])
    out = clinical._hai_specimens(Cohort.open(tmp_path), "us")
    assert out == {"spec-E1-0"}


@pytest.mark.unit
def test_hai_specimens_rejects_wrong_system(tmp_path: Path) -> None:
    """Canonical equality on HAI_EVENT_ID_SYSTEM — same defense pattern
    as canonical SNOMED URI from PR #113 C3."""
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "specimen": {"reference": "Specimen/spec-E1-0"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}],
            },
            "identifier": [{"system": "http://other/system",
                            "value": "hai-clabsi-1"}],
        },
    ])
    out = clinical._hai_specimens(Cohort.open(tmp_path), "us")
    assert out == set()


@pytest.mark.unit
def test_hai_specimens_rejects_empty_value(tmp_path: Path) -> None:
    """Identifier with correct system but empty value is not a HAI marker."""
    from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "specimen": {"reference": "Specimen/spec-E1-0"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}],
            },
            "identifier": [{"system": HAI_EVENT_ID_SYSTEM, "value": ""}],
        },
    ])
    out = clinical._hai_specimens(Cohort.open(tmp_path), "us")
    assert out == set()


@pytest.mark.unit
def test_hai_specimens_rejects_malformed_value(tmp_path: Path) -> None:
    """pr117-adv-1 Agent 1 IMPORTANT #3: identifier with correct system but
    value not matching the `hai-` prefix convention is not a HAI marker.
    Truthy-only check accepted whitespace / arbitrary placeholders, which
    would silently inflate hai_specs."""
    from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            "specimen": {"reference": "Specimen/spec-E1-0"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}],
            },
            # Malformed: not starting with "hai-"
            "identifier": [{"system": HAI_EVENT_ID_SYSTEM, "value": "placeholder"}],
        },
        {
            "resourceType": "Observation",
            "id": "mb-org-E2-0",
            "encounter": {"reference": "Encounter/E2"},
            "specimen": {"reference": "Specimen/spec-E2-0"},
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}],
            },
            # Whitespace-only
            "identifier": [{"system": HAI_EVENT_ID_SYSTEM, "value": " "}],
        },
    ])
    out = clinical._hai_specimens(Cohort.open(tmp_path), "us")
    assert out == set(), (
        f"malformed identifier value must be rejected (silent-no-op defense); "
        f"got {out}"
    )


@pytest.mark.unit
def test_hai_specimens_skips_missing_specimen_ref(tmp_path: Path) -> None:
    """pr117-adv-1 Agent 3 LOW: defensive `if spec_id:` branch — mb-org-*
    with HAI identifier but no specimen.reference must skip silently
    (rather than add empty string to the set)."""
    from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation",
            "id": "mb-org-E1-0",
            "encounter": {"reference": "Encounter/E1"},
            # no specimen.reference
            "code": {"coding": [{"code": "600-7"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "3092008"}],
            },
            "identifier": [{"system": HAI_EVENT_ID_SYSTEM, "value": "hai-orphan-1"}],
        },
    ])
    out = clinical._hai_specimens(Cohort.open(tmp_path), "us")
    assert out == set()


@pytest.mark.unit
def test_hai_specimens_empty_file(tmp_path: Path) -> None:
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    out = clinical._hai_specimens(Cohort.open(tmp_path), "us")
    assert out == set()


@pytest.mark.unit
def test_hai_event_id_system_canonical_constant_shared() -> None:
    """Canonical-constant contract: writer (_fhir_microbiology) and reader
    (clinical) import the same HAI_EVENT_ID_SYSTEM. Renaming triggers
    ImportError downstream, not a silent gate skip."""
    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.modules.output._fhir_microbiology import HAI_EVENT_ID_SYSTEM

    assert HAI_EVENT_ID_SYSTEM == "urn:clinosim:identifier:hai-event-id"
    assert clinical_axis.HAI_EVENT_ID_SYSTEM is HAI_EVENT_ID_SYSTEM
