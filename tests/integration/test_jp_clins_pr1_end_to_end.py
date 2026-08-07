"""Integration test — P2-13 PR1: JP-CLINS profile URL emission at cohort scale.

Runs a small country=JP cohort (p=100 seed=42, snapshot end=2026-06-30),
verifies:
- 5 JP-CLINS-registered resource types (Condition, AllergyIntolerance,
  Observation.laboratory, MedicationRequest, Procedure) carry JP-CLINS
  eCS profile URLs
- Observation filter honored (lab-only)
- MedicationRequest filter honored (Issue #445): a prescription with no dose
  and no route cannot satisfy the eCS `dosageInstruction` min=1 constraint, so
  it withholds the eCS URL and keeps only the parent JP Core profile. Both
  sides are asserted — the excluded rows must not claim eCS AND must retain
  JP Core.
- DiagnosticReport is NOT in JP-CLINS scope; it must NOT carry any
  JP-CLINS profile URL even for lab category
- No profile URLs leak into country=US cohort
- AllergyIntolerance may be sparse or absent at p=100 (single-digit %
  prevalence in the general population); when the pool is empty, the
  profile check is vacuously satisfied. All other four resource types
  are expected to have non-empty pools.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration._sr_helpers import run_generate

_JP_CLINS_PROFILE_ROOT = "http://jpfhir.jp/fhir/eCS/StructureDefinition/"
_SNAPSHOT_END = "2026-06-30"


def _load_resources(outdir: Path) -> dict[str, list[dict]]:
    resources_by_type: dict[str, list[dict]] = {}
    for ndjson_path in sorted(outdir.rglob("*.ndjson")):
        with open(ndjson_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                rt = r.get("resourceType", "")
                if not rt:
                    continue
                resources_by_type.setdefault(rt, []).append(r)
    return resources_by_type


@pytest.mark.integration
def test_jp_p100_carries_clins_profiles_on_five_types(tmp_path):
    outdir = tmp_path / "jp"
    run_generate("JP", 100, 42, outdir, end=_SNAPSHOT_END)
    resources_by_type = _load_resources(outdir)

    from clinosim.modules.output._fhir_post_process import (
        _JP_CLINS_PROFILES,
        _is_lab_observation,
        _medication_request_satisfies_ecs,
    )

    # Dense resource types — expected to have at least one instance at p=100.
    dense_types = {"Condition", "Observation", "MedicationRequest", "Procedure"}
    # AllergyIntolerance is sparse (single-digit % prevalence in the general
    # population); the profile check is vacuous if the pool is empty.
    for rt in _JP_CLINS_PROFILES:
        pool = resources_by_type.get(rt, [])
        if rt == "Observation":
            pool = [r for r in pool if _is_lab_observation(r)]
        if rt == "MedicationRequest":
            # Issue #445: eCS raises `dosageInstruction` to min=1 while the parent JP Core
            # profile leaves it at min=0, so a prescription that carries no dose and no
            # route in CIF cannot satisfy eCS and deliberately does not claim it. Same
            # narrowing shape as the `_is_lab_observation` filter above, and it reuses the
            # PRODUCTION predicate so this test cannot drift into a second definition of
            # "eCS-eligible".
            #
            # Issue #452 PR 2 (2026-08-05): `HomeMedication` now carries route / dose /
            # frequency through `_derive_home_medications` and `_deactivate_to_layer1` to
            # both the outpatient renewal (`outpatient.py`) and inpatient discharge
            # chronic-transcribe (`inpatient.py`) sites. The pathway that produced
            # dosage-less prescriptions in production cohorts is no longer exercised at
            # this seed / population. The withholding logic remains defensive for edge
            # cases (e.g. a future YAML omitting route on a chronic drug), so an empty
            # `ecs_ineligible` pool is informational rather than a regression.
            ecs_ineligible = [r for r in pool if not _medication_request_satisfies_ecs(r)]
            pool = [r for r in pool if _medication_request_satisfies_ecs(r)]
            # Pin BOTH sides of the narrowing when the pool is non-empty. Asserting only
            # "does not claim eCS" would still pass if the resource had also lost its
            # parent JP Core profile, which would be a silent conformance regression
            # rather than a deliberate withholding.
            jp_core_mr = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest"
            for r in ecs_ineligible:
                profs = r.get("meta", {}).get("profile", [])
                assert _JP_CLINS_PROFILES[rt][0] not in profs, (
                    f"{rt}/{r.get('id')} claims eCS with no dosageInstruction (min=1 violation)"
                )
                assert jp_core_mr in profs, f"{rt}/{r.get('id')} lost the parent JP Core profile"
        if rt in dense_types:
            assert pool, f"expected dense JP-CLINS type {rt} non-empty at p=100 JP"
        for r in pool:
            profs = r.get("meta", {}).get("profile", [])
            expected = _JP_CLINS_PROFILES[rt][0]
            assert expected in profs, f"{rt}/{r.get('id')} missing {expected}"


@pytest.mark.integration
def test_jp_p100_diagnostic_report_has_no_clins_profile(tmp_path):
    """JP-CLINS v1.12.0 does not publish a DiagnosticReport profile — must not emit."""
    outdir = tmp_path / "jp-dr"
    run_generate("JP", 100, 42, outdir, end=_SNAPSHOT_END)
    resources_by_type = _load_resources(outdir)
    for r in resources_by_type.get("DiagnosticReport", []):
        profs = r.get("meta", {}).get("profile", [])
        assert not any(p.startswith(_JP_CLINS_PROFILE_ROOT) for p in profs), (
            f"DiagnosticReport {r.get('id')} leaked JP-CLINS profile: {profs}"
        )


@pytest.mark.integration
def test_us_p50_has_no_clins_profile(tmp_path):
    outdir = tmp_path / "us"
    run_generate("US", 50, 42, outdir, end=_SNAPSHOT_END)
    for ndjson_path in sorted(outdir.rglob("*.ndjson")):
        with open(ndjson_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                profs = r.get("meta", {}).get("profile", [])
                assert not any(p.startswith(_JP_CLINS_PROFILE_ROOT) for p in profs), (
                    f"US cohort leaked JP-CLINS profile: {r['resourceType']}/{r.get('id')} → {profs}"
                )
