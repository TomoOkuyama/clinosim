"""Issue #345 — exhaustive enumeration CLI subcommand.

Discovery + expansion + manifest + coverage-explosion guard + deterministic
seed derivation. Execution is smoke-tested at L1 (78 patients) in a
separate integration test to keep unit-test wall-clock small.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest
import yaml

from clinosim.simulator.enumerate import (
    _COVERAGE_EXPLOSION_THRESHOLD,
    _MANIFEST_SCHEMA_VERSION,
    CoverageExplosionError,
    EnumerationCase,
    active_severity_levels,
    build_manifest,
    check_coverage_size,
    derive_case_seed,
    discover_disease_scenarios,
    discover_encounter_scenarios,
    expand_cases,
    make_patient_id,
    plan_enumeration,
    read_course_archetypes,
    read_severity_distribution,
)

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DISEASE_DIR = _REPO_ROOT / "clinosim" / "modules" / "disease" / "reference_data"
_ENCOUNTER_DIR = _REPO_ROOT / "clinosim" / "modules" / "encounter" / "reference_data"


# === naming unification helpers ===


def test_read_severity_distribution_reads_disease_nested_shape() -> None:
    """Disease YAML nests severity distribution under `severity.distribution`."""
    data = {"severity": {"distribution": {"mild": 0.3, "moderate": 0.5, "severe": 0.2}}}
    result = read_severity_distribution(data, "disease")
    assert result == {"mild": 0.3, "moderate": 0.5, "severe": 0.2}


def test_read_severity_distribution_reads_encounter_top_level_shape() -> None:
    """Encounter YAML uses `severity_distribution` at the top level."""
    data = {"severity_distribution": {"mild": 0.5, "severe": 0.5}}
    result = read_severity_distribution(data, "encounter")
    assert result == {"mild": 0.5, "severe": 0.5}


def test_read_severity_distribution_returns_empty_on_missing() -> None:
    assert read_severity_distribution({}, "disease") == {}
    assert read_severity_distribution({}, "encounter") == {}


def test_read_severity_distribution_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown scenario kind"):
        read_severity_distribution({}, "invalid")  # type: ignore[arg-type]


def test_read_course_archetypes_dict() -> None:
    data = {"course_archetypes": {"smooth_recovery": {}, "sudden_deterioration": {}}}
    assert set(read_course_archetypes(data).keys()) == {"smooth_recovery", "sudden_deterioration"}


def test_active_severity_levels_canonical_order() -> None:
    """`mild → moderate → severe` order preserved; unknown vocabulary sorted alphabetically after."""
    dist = {"severe": 0.2, "mild": 0.3, "moderate": 0.5}
    assert active_severity_levels(dist) == ["mild", "moderate", "severe"]


def test_active_severity_levels_skips_zero_prob() -> None:
    dist = {"mild": 0.0, "moderate": 1.0, "severe": 0.0}
    assert active_severity_levels(dist) == ["moderate"]


# === Auto-discovery: every YAML on disk is picked up ===


def test_disease_discovery_covers_every_yaml_on_disk() -> None:
    """Every disease YAML file in `disease/reference_data/` appears in
    `discover_disease_scenarios()`. Adding a new YAML makes it show up
    without any code change."""
    yaml_ids: set[str] = set()
    for p in sorted(glob.glob(str(_DISEASE_DIR / "*.yaml"))):
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        did = data.get("disease_id")
        if did and did != "disease_id":
            yaml_ids.add(did)
    discovered_ids = {s.scenario_id for s in discover_disease_scenarios()}
    assert discovered_ids == yaml_ids, (
        f"disease discovery drift: missing from discovery = {yaml_ids - discovered_ids}, "
        f"missing from disk = {discovered_ids - yaml_ids}"
    )


def test_encounter_discovery_covers_every_yaml_on_disk() -> None:
    yaml_ids: set[str] = set()
    for p in sorted(glob.glob(str(_ENCOUNTER_DIR / "*.yaml"))):
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        cid = data.get("condition_id")
        if cid:
            yaml_ids.add(cid)
    discovered_ids = {s.scenario_id for s in discover_encounter_scenarios()}
    assert discovered_ids == yaml_ids


def test_all_disease_yamls_have_course_archetypes() -> None:
    """Enumerable validation guard: every disease YAML must declare
    `course_archetypes` (non-empty dict). If a future YAML omits it, the
    enumeration would silently collapse to a single pattern — this test
    fails first."""
    scenarios = discover_disease_scenarios()
    offenders = [s.scenario_id for s in scenarios if not s.archetype_keys]
    assert not offenders, f"disease YAMLs missing course_archetypes: {offenders}"


def test_all_disease_yamls_have_severity_distribution() -> None:
    scenarios = discover_disease_scenarios()
    offenders = [s.scenario_id for s in scenarios if not s.severity_levels]
    assert not offenders, f"disease YAMLs missing severity.distribution: {offenders}"


# === Case expansion counts ===


def test_l1_basic_count_matches_scenario_count() -> None:
    """L1 = 1 case per scenario. Total = discovered_diseases + discovered_encounters."""
    diseases = discover_disease_scenarios()
    encounters = discover_encounter_scenarios()
    cases = expand_cases(diseases + encounters, "basic", "JP")
    assert len(cases) == len(diseases) + len(encounters)


def test_l2_severity_count_sums_severity_levels() -> None:
    diseases = discover_disease_scenarios()
    encounters = discover_encounter_scenarios()
    cases = expand_cases(diseases + encounters, "severity", "JP")
    expected = sum(len(s.severity_levels) or 1 for s in diseases + encounters)
    assert len(cases) == expected


def test_l3_full_count_multiplies_severity_by_archetypes_plus_complications() -> None:
    """L3 for diseases = severity × archetype cartesian + one extra case per
    (disease × complication) with default severity/archetype.
    L3 for encounters = severity axis only (no archetypes, no complications)."""
    diseases = discover_disease_scenarios()
    encounters = discover_encounter_scenarios()
    cases = expand_cases(diseases + encounters, "full", "JP")
    expected_d_sev_arch = sum(len(s.severity_levels) * max(len(s.archetype_keys), 1) for s in diseases)
    expected_d_comp = sum(len(s.complication_names) for s in diseases)
    expected_e = sum(len(s.severity_levels) or 1 for s in encounters)
    assert len(cases) == expected_d_sev_arch + expected_d_comp + expected_e


def test_l3_full_includes_complication_axis_per_disease() -> None:
    """Every complication declared in every disease YAML appears as at least
    one case at level=full. Regression pin: adding a new complication to any
    disease YAML surfaces automatically."""
    diseases = discover_disease_scenarios()
    encounters = discover_encounter_scenarios()
    cases = expand_cases(diseases + encounters, "full", "JP")
    # Every (disease, complication) pair from discovery must have at least
    # one case whose complication field matches.
    expected_pairs = {(d.scenario_id, c) for d in diseases for c in d.complication_names}
    observed_pairs = {(c.scenario_id, c.complication) for c in cases if c.complication}
    missing = expected_pairs - observed_pairs
    assert not missing, f"complication cases missing from L3 expansion: {missing}"


def test_l3_complication_cases_use_default_severity_and_archetype() -> None:
    """Complication axis cases pin severity + archetype at canonical defaults
    (severity_levels[0], archetype_keys[0]) so the coverage growth is
    linear in complication count, not cartesian with severity × archetype
    (that would explode past the coverage guard)."""
    diseases = discover_disease_scenarios()
    cases = expand_cases(diseases, "full", "JP")
    for c in cases:
        if not c.complication:
            continue
        # Find the source disease
        src = next(d for d in diseases if d.scenario_id == c.scenario_id)
        assert c.severity == src.severity_levels[0]
        assert c.archetype == src.archetype_keys[0]


def test_l2_severity_does_not_include_complication_axis() -> None:
    """The complication axis is level=full only; L2 severity keeps the
    linear severity expansion (no complication cases added)."""
    diseases = discover_disease_scenarios()
    cases = expand_cases(diseases, "severity", "JP")
    assert all(not c.complication for c in cases), "L2 must not emit complication-axis cases (that is L3-only)"


def test_expand_cases_rejects_unknown_level() -> None:
    """Unknown level raises ValueError. Use a non-empty scenario list so the
    expansion loop actually executes (an empty list would short-circuit the
    per-scenario dispatch and hide the guard)."""
    from clinosim.simulator.enumerate import DiscoveredScenario

    scenarios = [
        DiscoveredScenario(
            kind="disease",
            scenario_id="x",
            yaml_path="",
            severity_levels=("moderate",),
            archetype_keys=("a",),
        )
    ]
    with pytest.raises(ValueError, match="unknown level"):
        expand_cases(scenarios, "invalid", "JP")  # type: ignore[arg-type]


# === Both countries ===


def test_plan_enumeration_both_countries_doubles_cases() -> None:
    jp = plan_enumeration(level="full", countries=["JP"])
    both = plan_enumeration(level="full", countries=["JP", "US"], bypass_size_guard=True)
    assert len(both.cases) == 2 * len(jp.cases)


# === Coverage-explosion guard ===


def test_coverage_guard_raises_above_threshold_without_bypass() -> None:
    """Fake case list exceeding the threshold to keep the test fast."""
    cases = [
        EnumerationCase(kind="disease", scenario_id=f"x{i}", severity="moderate", archetype="a", country="JP")
        for i in range(_COVERAGE_EXPLOSION_THRESHOLD + 1)
    ]
    with pytest.raises(CoverageExplosionError, match="threshold"):
        check_coverage_size(cases, bypass_size_guard=False)


def test_coverage_guard_passes_below_threshold() -> None:
    cases = [
        EnumerationCase(kind="disease", scenario_id=f"x{i}", severity="moderate", archetype="a", country="JP")
        for i in range(_COVERAGE_EXPLOSION_THRESHOLD - 1)
    ]
    check_coverage_size(cases, bypass_size_guard=False)  # no raise


def test_coverage_guard_bypass_allows_large_count() -> None:
    cases = [
        EnumerationCase(kind="disease", scenario_id=f"x{i}", severity="moderate", archetype="a", country="JP")
        for i in range(_COVERAGE_EXPLOSION_THRESHOLD + 100)
    ]
    check_coverage_size(cases, bypass_size_guard=True)  # no raise


# === Deterministic seed derivation ===


def test_derive_case_seed_deterministic() -> None:
    case = EnumerationCase(
        kind="disease",
        scenario_id="bacterial_pneumonia",
        severity="moderate",
        archetype="smooth_recovery",
        country="JP",
    )
    a = derive_case_seed(42, case)
    b = derive_case_seed(42, case)
    assert a == b


def test_derive_case_seed_differs_for_different_cases() -> None:
    c1 = EnumerationCase(kind="disease", scenario_id="a", severity="mild", archetype="x", country="JP")
    c2 = EnumerationCase(kind="disease", scenario_id="b", severity="mild", archetype="x", country="JP")
    assert derive_case_seed(42, c1) != derive_case_seed(42, c2)


def test_derive_case_seed_differs_for_different_base_seeds() -> None:
    case = EnumerationCase(kind="disease", scenario_id="a", severity="mild", archetype="x", country="JP")
    assert derive_case_seed(42, case) != derive_case_seed(43, case)


# === Manifest completeness ===


def test_build_manifest_maps_every_case_to_a_patient_id() -> None:
    cases = [
        EnumerationCase(kind="disease", scenario_id="a", severity="mild", archetype="x", country="JP"),
        EnumerationCase(kind="encounter", scenario_id="b", severity="moderate", archetype="", country="JP"),
    ]
    ids = ["ENUM-JP-0001", "ENUM-JP-0002"]
    m = build_manifest(cases, ids, level="full", countries=["JP"], base_seed=42, generated_at="t")
    assert m.total_patients == 2
    assert [c.patient_id for c in m.cases] == ids
    assert [c.scenario_id for c in m.cases] == ["a", "b"]
    assert m.schema_version == _MANIFEST_SCHEMA_VERSION


def test_build_manifest_rejects_length_mismatch() -> None:
    cases = [EnumerationCase(kind="disease", scenario_id="a", severity="mild", archetype="x", country="JP")]
    with pytest.raises(ValueError, match="length mismatch"):
        build_manifest(cases, [], level="full", countries=["JP"], base_seed=42, generated_at="t")


def test_make_patient_id_stable_format() -> None:
    case = EnumerationCase(kind="disease", scenario_id="a", severity="mild", archetype="x", country="JP")
    assert make_patient_id(1, case) == "ENUM-JP-0001"
    assert make_patient_id(590, case) == "ENUM-JP-0590"


# === Issue #351: encounter-axis Patient names non-empty ===


def test_enumerate_encounter_patient_populates_family_and_given_names() -> None:
    """Issue #351 regression pin: encounter-axis PersonRecord in
    `run_enumeration` must populate `family_name` and `given_name`.

    Without this, the emitted `Patient.name` on encounter-axis patients
    carries `family=""` and `given=[""]` with an iso21090 IDE marker
    (kanji representation asserted but no actual kanji present) — 104
    validation errors on v17 enumerate cohort (96% of total).

    We run a single-case plan through `run_enumeration` and assert the
    resulting PatientProfile carries non-empty names. Disease path is
    covered by `run_forced` which sets its own defaults; the fix is
    specifically for the encounter branch.
    """
    from clinosim.simulator.enumerate import EnumerationPlan, run_enumeration

    # Pick any encounter scenario — the fix is generic across all of them.
    encounters = discover_encounter_scenarios()
    assert encounters, "must have at least one encounter scenario discovered"
    encounter = encounters[0]

    case = EnumerationCase(
        kind="encounter",
        scenario_id=encounter.scenario_id,
        severity=encounter.severity_levels[0],
        archetype="",
        country="JP",
    )
    plan = EnumerationPlan(cases=[case], countries=["JP"], level="full", base_seed=42)
    dataset, manifest = run_enumeration(plan)

    assert len(dataset.patients) == 1
    patient = dataset.patients[0].patient
    # PatientProfile.name is a nested PersonName dataclass with family_name /
    # given_name fields (see `clinosim.types.patient.PersonName`).
    assert patient.name.family_name, (
        f"Issue #351: encounter-axis Patient must have non-empty family_name, got {patient.name.family_name!r}"
    )
    assert patient.name.given_name, (
        f"Issue #351: encounter-axis Patient must have non-empty given_name, got {patient.name.given_name!r}"
    )
