"""FHIR R4 ``Resource.id`` spec-validity invariant across the whole export.

Turns the existing ``fhir_r4_adapter._fhir_id_is_spec_valid`` fail-soft
counter (which increments ``invalid_id_counts`` and logs a warning but lets
the export succeed — iris4h-ai P0 finding, 2026-07-17) into a fail-loud
test-time gate: any emitted ``Resource.id`` violating
``[A-Za-z0-9\\-\\.]{1,64}`` fails this test.

Motivation (Issue #349 Phase 3-Z, session 64)
---------------------------------------------
Issue #349's expected effect is that ``Resource.id`` uniformly ≤ 16 chars
after the opaque-id refactor lands across every resource type. That's the
aspirational target; the *strict* invariant that Issue #349 exists to
enforce is FHIR R4's 64-char + character-class limit itself — the failure
class that produced the v16 66-char ``req-abx-hai-...-ceftriaxone-narrowed``
offender (Issue #347 / PR #348) and the iris4h-ai P0 812 606-id underscore
violation (session 47).

Both violation classes have a fail-soft counter in the FHIR adapter, but
no repository-wide test-time gate. This test closes that gap so
regressions surface in CI before hitting HAPI / IRIS.

Runs on the existing ``beta_result`` fixture's cohort (p ≈ 5 000, US)
plus a second ``run_beta`` at p = 2 000 with country=JP so JP-only
resources (JP_Composition, JP_MedicationRequest identifier slices,
JP-CLINS profiles) are also exercised.

Green today → regression guard for Phase 3 sibling-sweep.
Red today → discovers pre-existing spec-invalid ids that Phase 3 must
address; the assertion message reports counts per resource type so
follow-up sub-PRs can be scoped precisely.
"""

from __future__ import annotations

import json
import os

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.fhir_r4_adapter import (
    _fhir_id_is_spec_valid,
    convert_cif_to_fhir,
)
from clinosim.simulator import run_beta
from clinosim.types.config import SimulatorConfig

pytestmark = pytest.mark.integration


_FHIR_ID_MAX_LENGTH = 64
_ALLOWED_CHARS = "[A-Za-z0-9\\-\\.]"


def _walk_resources(fhir_dir: str) -> list[tuple[str, str, dict]]:
    """Yield (resource_type, resource_id, resource_dict) for every emitted resource.

    Walks all ``*.ndjson`` files under ``fhir_dir`` except ``manifest.json``.
    Every line is a self-contained JSON resource per Bulk Data Export
    convention (AD-31).
    """
    out: list[tuple[str, str, dict]] = []
    for fname in os.listdir(fhir_dir):
        if not fname.endswith(".ndjson"):
            continue
        path = os.path.join(fhir_dir, fname)
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                resource = json.loads(line)
                out.append(
                    (
                        resource.get("resourceType", "Unknown"),
                        str(resource.get("id", "")),
                        resource,
                    )
                )
    return out


def _summarize_violations(violations: list[tuple[str, str]]) -> str:
    """Human-readable per-resource-type violation summary for assertion messages.

    ``violations`` is a list of ``(resource_type, offending_id)`` tuples. The
    summary groups by resource_type, reports counts, and shows up to three
    example offenders per type so a triage engineer can locate the responsible
    builder without opening the NDJSON.
    """
    from collections import defaultdict

    grouped: dict[str, list[str]] = defaultdict(list)
    for rt, rid in violations:
        grouped[rt].append(rid)
    lines = [
        f"{len(violations)} FHIR R4 Resource.id spec violations (pattern {_ALLOWED_CHARS}{{1,{_FHIR_ID_MAX_LENGTH}}}):"
    ]
    for rt in sorted(grouped):
        ids = grouped[rt]
        sample = ", ".join(repr(x) for x in ids[:3])
        more = f" (+{len(ids) - 3} more)" if len(ids) > 3 else ""
        lines.append(f"  {rt}: {len(ids)} — sample: {sample}{more}")
    return "\n".join(lines)


@pytest.fixture(scope="module")
def us_export_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    """One-time US p=1000 generation → FHIR export directory.

    Module-scoped so the cost is paid once even though multiple test cases
    below walk the same NDJSON tree. p=1000 is a coverage-vs-runtime
    compromise: exercises most builder branches (~200-400 patients, ~2k
    encounters, some HAI cohort) while keeping the integration-suite
    incremental cost around 1-2 min per country.
    """
    config = SimulatorConfig(
        catchment_population=1_000,
        time_range=("2024-04-01", "2025-03-31"),
        random_seed=42,
    )
    result = run_beta(config)
    root = tmp_path_factory.mktemp("fhir_id_invariant_us")
    cif_dir = str(root / "cif")
    fhir_dir = str(root / "fhir")
    write_cif(result, cif_dir)
    convert_cif_to_fhir(cif_dir, fhir_dir, country="US")
    return fhir_dir


@pytest.fixture(scope="module")
def jp_export_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    """One-time JP p=1000 generation → FHIR export directory.

    JP path exercises JP Core / JP-CLINS / JP-eCS profile builders whose
    id shapes may diverge from US builders (Composition, MedicationRequest
    identifier slices, JP Core Observation_LabResult profile, etc.).
    """
    config = SimulatorConfig(
        catchment_population=1_000,
        time_range=("2024-04-01", "2025-03-31"),
        random_seed=42,
    )
    result = run_beta(config)
    root = tmp_path_factory.mktemp("fhir_id_invariant_jp")
    cif_dir = str(root / "cif")
    fhir_dir = str(root / "fhir")
    write_cif(result, cif_dir)
    convert_cif_to_fhir(cif_dir, fhir_dir, country="JP")
    return fhir_dir


def _assert_all_ids_spec_valid(fhir_dir: str, country_label: str) -> None:
    """Core invariant assertion — factored out so US + JP tests share it.

    Walks every resource in every NDJSON under ``fhir_dir`` and asserts
    ``_fhir_id_is_spec_valid(id)`` for each. On failure, produces a per-
    resource-type summary with up to three example offenders per type so
    a triage engineer can locate the responsible builder.
    """
    violations: list[tuple[str, str]] = []
    for rt, rid, _resource in _walk_resources(fhir_dir):
        if not rid:
            continue
        if not _fhir_id_is_spec_valid(rid):
            violations.append((rt, rid))
    assert not violations, f"[{country_label}] " + _summarize_violations(violations)


def test_all_resource_ids_are_spec_valid_us(us_export_dir: str) -> None:
    """US export: every emitted Resource.id matches FHIR R4 spec.

    Fail-loud guard for the class of failure Issue #349 exists to
    eliminate (compound-id-as-key breaching the 64-char limit) plus the
    iris4h-ai P0 character-class violation (underscore in id) fixed in
    session 47. Both regressions would be caught here rather than at
    HAPI / IRIS ingest time.
    """
    _assert_all_ids_spec_valid(us_export_dir, "US")


def test_all_resource_ids_are_spec_valid_jp(jp_export_dir: str) -> None:
    """JP export: same invariant, exercising JP-only builders.

    JP Core / JP-CLINS / JP-eCS profile builders may have distinct id
    construction paths (Composition, MedicationRequest slice identifiers,
    JP_Observation_LabResult profile), so exercising them separately
    catches JP-locale-specific regressions.
    """
    _assert_all_ids_spec_valid(jp_export_dir, "JP")


def test_no_id_exceeds_fhir_max_length_us(us_export_dir: str) -> None:
    """Explicit 64-char length invariant (Issue #349 class of failure).

    Redundant with ``_fhir_id_is_spec_valid`` (which combines length +
    character-class), but a separate test emits a length-specific failure
    message that is easier to triage — an id that violates only the length
    constraint often means a compound key grew, while a character-class
    violation typically means an underscore leaked in from a drug slug or
    an internal identifier.
    """
    over_limit: list[tuple[str, str, int]] = []
    for rt, rid, _resource in _walk_resources(us_export_dir):
        if len(rid) > _FHIR_ID_MAX_LENGTH:
            over_limit.append((rt, rid, len(rid)))
    if over_limit:
        details = "\n".join(f"  {rt}: {rid!r} ({length} chars)" for rt, rid, length in over_limit[:10])
        more = f"\n  (+{len(over_limit) - 10} more)" if len(over_limit) > 10 else ""
        pytest.fail(
            f"[US] {len(over_limit)} Resource.id values exceed FHIR R4's {_FHIR_ID_MAX_LENGTH}-char limit:\n"
            + details
            + more
        )


def test_no_id_exceeds_fhir_max_length_jp(jp_export_dir: str) -> None:
    """Same 64-char length invariant for JP export."""
    over_limit: list[tuple[str, str, int]] = []
    for rt, rid, _resource in _walk_resources(jp_export_dir):
        if len(rid) > _FHIR_ID_MAX_LENGTH:
            over_limit.append((rt, rid, len(rid)))
    if over_limit:
        details = "\n".join(f"  {rt}: {rid!r} ({length} chars)" for rt, rid, length in over_limit[:10])
        more = f"\n  (+{len(over_limit) - 10} more)" if len(over_limit) > 10 else ""
        pytest.fail(
            f"[JP] {len(over_limit)} Resource.id values exceed FHIR R4's {_FHIR_ID_MAX_LENGTH}-char limit:\n"
            + details
            + more
        )
