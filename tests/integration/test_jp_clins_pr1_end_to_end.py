"""Integration test — P2-13 PR1: JP-CLINS profile URL emission at cohort scale.

Runs a small country=JP cohort (p=100 seed=42, snapshot end=2026-06-30),
verifies:
- 5 JP-CLINS-registered resource types (Condition, AllergyIntolerance,
  Observation.laboratory, MedicationRequest, Procedure) carry JP-CLINS
  eCS profile URLs
- Observation filter honored (lab-only)
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

    from clinosim.modules.output.fhir_r4_adapter import (
        _JP_CLINS_PROFILES,
        _is_lab_observation,
    )

    # Dense resource types — expected to have at least one instance at p=100.
    dense_types = {"Condition", "Observation",
                   "MedicationRequest", "Procedure"}
    # AllergyIntolerance is sparse (single-digit % prevalence in the general
    # population); the profile check is vacuous if the pool is empty.
    for rt in _JP_CLINS_PROFILES:
        pool = resources_by_type.get(rt, [])
        if rt == "Observation":
            pool = [r for r in pool if _is_lab_observation(r)]
        if rt in dense_types:
            assert pool, (
                f"expected dense JP-CLINS type {rt} non-empty at p=100 JP"
            )
        for r in pool:
            profs = r.get("meta", {}).get("profile", [])
            expected = _JP_CLINS_PROFILES[rt][0]
            assert expected in profs, (
                f"{rt}/{r.get('id')} missing {expected}"
            )


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
                    "US cohort leaked JP-CLINS profile: "
                    f"{r['resourceType']}/{r.get('id')} → {profs}"
                )
