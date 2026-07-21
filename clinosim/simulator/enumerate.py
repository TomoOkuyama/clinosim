"""Exhaustive enumeration mode for debug and comprehensive validation coverage.

Generates exactly one patient for every combination of (disease × severity ×
course_archetype) plus every (encounter × severity). Suitable for
comprehensive FHIR validation, template narrative rendering inspection, and
regression detection when new disease/encounter YAMLs are added.

Design contract (see Issue #345):

1. **YAML-driven discovery** — never hardcode scenario IDs, severity
   vocabularies, or archetype keys. Any new YAML in
   `disease/reference_data/` or `encounter/reference_data/` is picked up
   automatically on the next enumeration run.
2. **Per-scenario attribute extraction** — read `severity` and
   `course_archetypes` keys from each YAML at runtime.
3. **Coverage-explosion guard** — refuse to run if the case count exceeds
   `_COVERAGE_EXPLOSION_THRESHOLD` without explicit `bypass_size_guard`.
4. **Manifest completeness** — the emitted `enumeration_manifest.json`
   includes every enumerated case.

Naming unification:

The existing YAML shapes have an inconsistency:
- Disease YAML: `severity.distribution` (nested under `severity` dict)
- Encounter YAML: `severity_distribution` (top-level field)

`read_severity_distribution(protocol_data, kind)` hides the difference at
the enumeration-access layer. Renaming YAML fields is a breaking change
tracked separately as a follow-up.
"""

from __future__ import annotations

import glob
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DISEASE_REFERENCE_DIR = _REPO_ROOT / "clinosim" / "modules" / "disease" / "reference_data"
_ENCOUNTER_REFERENCE_DIR = _REPO_ROOT / "clinosim" / "modules" / "encounter" / "reference_data"

# Coverage-explosion guard. If the enumerated case count exceeds this
# threshold the CLI requires an explicit `--yes-large` / `bypass_size_guard`
# to run — protects against a future orthogonal axis (HAI / diagnosis
# outcome / chronic overlay) being added carelessly and producing tens of
# thousands of cases silently.
_COVERAGE_EXPLOSION_THRESHOLD = 2000

# Enumeration schema version — bumped on any breaking change to
# `enumeration_manifest.json`.
_MANIFEST_SCHEMA_VERSION = "1"

# Fixed base date for enumeration case generation. All enumerated cases use
# the same date so downstream diffs across enumeration runs stay stable
# (independent of wall-clock time).
_ENUMERATION_BASE_DATE = "2024-06-15"

ScenarioKind = Literal["disease", "encounter"]
EnumerationLevel = Literal["basic", "severity", "full"]


# ---------------------------------------------------------------------------
# Naming unification helpers — hide the disease vs encounter shape difference
# ---------------------------------------------------------------------------


def read_severity_distribution(protocol_data: dict, kind: ScenarioKind) -> dict[str, float]:
    """Return the severity distribution dict for either scenario kind.

    Disease YAML nests it under `severity.distribution`.
    Encounter YAML uses `severity_distribution` at the top level.

    Returns an empty dict when the field is missing or non-dict. Empty-return
    triggers the enumerable-validation guard at load time — callers do not
    need to defend against missing keys.
    """
    if kind == "disease":
        sev = protocol_data.get("severity") if isinstance(protocol_data, dict) else None
        if isinstance(sev, dict):
            dist = sev.get("distribution")
            return dist if isinstance(dist, dict) else {}
        return {}
    if kind == "encounter":
        dist = protocol_data.get("severity_distribution") if isinstance(protocol_data, dict) else None
        return dist if isinstance(dist, dict) else {}
    raise ValueError(f"unknown scenario kind: {kind!r}")


def read_course_archetypes(protocol_data: dict) -> dict[str, dict]:
    """Return the course_archetypes dict (per-disease). Encounter YAMLs
    do not carry course_archetypes; this returns {} for encounters.

    Empty-return on a disease YAML triggers the enumerable-validation guard
    at load time.
    """
    arches = protocol_data.get("course_archetypes") if isinstance(protocol_data, dict) else None
    return arches if isinstance(arches, dict) else {}


def active_severity_levels(distribution: dict[str, float]) -> list[str]:
    """Return the severity levels with non-zero probability, in sorted order
    (mild → moderate → severe when present, then alphabetical for anything
    outside that vocabulary)."""
    keys = [k for k, v in distribution.items() if isinstance(v, (int, float)) and v > 0]
    canonical = ["mild", "moderate", "severe"]
    ordered = [k for k in canonical if k in keys]
    extras = sorted(k for k in keys if k not in canonical)
    return ordered + extras


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveredScenario:
    """A scenario discovered from YAML — before pattern expansion."""

    kind: ScenarioKind
    scenario_id: str  # disease_id for disease, condition_id for encounter
    yaml_path: str
    severity_levels: tuple[str, ...]
    archetype_keys: tuple[str, ...]  # empty for encounters
    complication_names: tuple[str, ...] = ()  # disease-only; complication `.name` values


def read_complications(protocol_data: dict) -> tuple[str, ...]:
    """Extract complication names from disease YAML.

    Disease `complications` is a list of dicts each with a `name` field
    (e.g. "parapneumonic_effusion"). The name is the id `ForcedScenario.
    complications` accepts to force the complication onto a patient's
    simulated inpatient record (`inpatient.py:complications_occurred`).

    Encounter YAMLs do not define complications; returns () for them.
    """
    comps = protocol_data.get("complications") if isinstance(protocol_data, dict) else None
    if not isinstance(comps, list):
        return ()
    names: list[str] = []
    for c in comps:
        if isinstance(c, dict):
            name = c.get("name")
            if isinstance(name, str) and name:
                names.append(name)
    return tuple(names)


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _validate_disease_yaml_enumerable(disease_id: str, data: dict, path: Path) -> None:
    """Fail-loud validation for enumerable disease YAMLs.

    An empty `severity.distribution` or `course_archetypes` would silently
    reduce the enumeration to a single pattern and hide the omission.
    """
    dist = read_severity_distribution(data, "disease")
    if not dist:
        raise ValueError(
            f"disease YAML {path.name} (disease_id={disease_id!r}) has empty or missing "
            f"`severity.distribution` — enumeration cannot expand severity levels. "
            f"Every disease YAML must declare `severity.distribution`."
        )
    arches = read_course_archetypes(data)
    if not arches:
        raise ValueError(
            f"disease YAML {path.name} (disease_id={disease_id!r}) has empty or missing "
            f"`course_archetypes` — enumeration cannot expand course archetypes. "
            f"Every disease YAML must declare `course_archetypes` as a non-empty dict."
        )


def _validate_encounter_yaml_enumerable(condition_id: str, data: dict, path: Path) -> None:
    """Enumerable validation for encounter YAMLs.

    Unlike diseases, encounters legitimately can lack a severity axis — e.g.
    scheduled outpatient visits (dialysis_session, mental_health_followup,
    rehabilitation_outpatient, smoking_cessation) where "mild vs severe"
    does not apply. For those the enumeration produces a single case with
    `severity="routine"` and no silent coverage reduction occurs (still one
    patient per encounter). Enumerable validation therefore accepts an
    empty distribution here; the caller sees `severity_levels=("routine",)`
    downstream.

    No fail-loud check is currently enforced on encounters — the discovery
    reader materializes a default severity and the case is still emitted.
    """
    return None


def discover_disease_scenarios() -> list[DiscoveredScenario]:
    """Scan `disease/reference_data/*.yaml` and return one DiscoveredScenario
    per file. Validates each YAML is enumerable — raises ValueError on any
    file that would silently reduce to a single pattern.
    """
    out: list[DiscoveredScenario] = []
    for path_str in sorted(glob.glob(str(_DISEASE_REFERENCE_DIR / "*.yaml"))):
        path = Path(path_str)
        data = _load_yaml(path)
        disease_id = data.get("disease_id")
        if not disease_id or disease_id == "disease_id":
            continue
        _validate_disease_yaml_enumerable(disease_id, data, path)
        dist = read_severity_distribution(data, "disease")
        arches = read_course_archetypes(data)
        comps = read_complications(data)
        out.append(
            DiscoveredScenario(
                kind="disease",
                scenario_id=disease_id,
                yaml_path=str(path.relative_to(_REPO_ROOT)),
                severity_levels=tuple(active_severity_levels(dist)),
                archetype_keys=tuple(sorted(arches.keys())),
                complication_names=comps,
            )
        )
    return out


def discover_encounter_scenarios() -> list[DiscoveredScenario]:
    """Scan `encounter/reference_data/*.yaml` and return one DiscoveredScenario
    per file. Validates each YAML is enumerable.
    """
    out: list[DiscoveredScenario] = []
    for path_str in sorted(glob.glob(str(_ENCOUNTER_REFERENCE_DIR / "*.yaml"))):
        path = Path(path_str)
        data = _load_yaml(path)
        condition_id = data.get("condition_id")
        if not condition_id:
            continue
        _validate_encounter_yaml_enumerable(condition_id, data, path)
        dist = read_severity_distribution(data, "encounter")
        levels = tuple(active_severity_levels(dist)) or ("routine",)
        out.append(
            DiscoveredScenario(
                kind="encounter",
                scenario_id=condition_id,
                yaml_path=str(path.relative_to(_REPO_ROOT)),
                severity_levels=levels,
                archetype_keys=(),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Case expansion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnumerationCase:
    """One patient's worth of enumeration input — the cartesian product of
    (scenario × severity × archetype) already expanded.

    `complication` is set (non-empty) for the additional complication axis
    cases at level=full: one extra case per (disease × complication) with
    severity/archetype at their canonical defaults. Set only for disease
    cases; encounters never carry a complication.
    """

    kind: ScenarioKind
    scenario_id: str
    severity: str
    archetype: str  # "" for encounters
    country: str
    complication: str = ""  # disease complication axis, "" when not applicable

    @property
    def case_key(self) -> str:
        """Stable string identifier used for deterministic seed derivation
        and for the patient_id suffix."""
        arch = self.archetype or "-"
        comp = self.complication or "-"
        return f"{self.country}:{self.kind}:{self.scenario_id}:{self.severity}:{arch}:{comp}"


def expand_cases(
    scenarios: list[DiscoveredScenario],
    level: EnumerationLevel,
    country: str,
) -> list[EnumerationCase]:
    """Expand scenarios to per-patient cases at the requested coverage level.

    - basic: 1 case per scenario (severity + archetype fields set to canonical defaults)
    - severity: 1 case per (scenario × severity)
    - full: 1 case per (disease × severity × archetype) + (encounter × severity)
    """
    cases: list[EnumerationCase] = []
    for s in scenarios:
        if level == "basic":
            severity = s.severity_levels[0] if s.severity_levels else "moderate"
            archetype = s.archetype_keys[0] if s.archetype_keys else ""
            cases.append(
                EnumerationCase(
                    kind=s.kind,
                    scenario_id=s.scenario_id,
                    severity=severity,
                    archetype=archetype,
                    country=country,
                )
            )
        elif level == "severity":
            severities = s.severity_levels or ("moderate",)
            for severity in severities:
                archetype = s.archetype_keys[0] if s.archetype_keys else ""
                cases.append(
                    EnumerationCase(
                        kind=s.kind,
                        scenario_id=s.scenario_id,
                        severity=severity,
                        archetype=archetype,
                        country=country,
                    )
                )
        elif level == "full":
            severities = s.severity_levels or ("moderate",)
            if s.kind == "disease":
                archetypes = s.archetype_keys or ("",)
                for severity in severities:
                    for archetype in archetypes:
                        cases.append(
                            EnumerationCase(
                                kind=s.kind,
                                scenario_id=s.scenario_id,
                                severity=severity,
                                archetype=archetype,
                                country=country,
                            )
                        )
                # Complications axis (Option A, session 63): add one extra
                # case per (disease × complication) with severity + archetype
                # at their canonical defaults. This exercises the
                # `ForcedScenario.complications` code path (inpatient.py:
                # `complications_occurred`) — an axis the cartesian
                # severity × archetype product does not cover on its own,
                # because complications are event-injected during the
                # inpatient loop rather than sampled from severity.
                default_severity = severities[0]
                default_archetype = archetypes[0]
                for complication in s.complication_names:
                    cases.append(
                        EnumerationCase(
                            kind=s.kind,
                            scenario_id=s.scenario_id,
                            severity=default_severity,
                            archetype=default_archetype,
                            country=country,
                            complication=complication,
                        )
                    )
            else:  # encounter
                for severity in severities:
                    cases.append(
                        EnumerationCase(
                            kind=s.kind,
                            scenario_id=s.scenario_id,
                            severity=severity,
                            archetype="",
                            country=country,
                        )
                    )
        else:
            raise ValueError(f"unknown level: {level!r}")
    return cases


# ---------------------------------------------------------------------------
# Deterministic seed derivation
# ---------------------------------------------------------------------------


def derive_case_seed(base_seed: int, case: EnumerationCase) -> int:
    """Derive a stable 32-bit sub-seed from the base seed + case key.

    Same (base_seed, case) always yields the same sub-seed; rerunning the
    enumeration produces byte-identical output.
    """
    payload = f"enumerate:{base_seed}:{case.case_key}".encode()
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:4], "big")


# ---------------------------------------------------------------------------
# Coverage-explosion guard
# ---------------------------------------------------------------------------


class CoverageExplosionError(Exception):
    """Raised when the enumerated case count exceeds the safety threshold
    without an explicit bypass."""


def check_coverage_size(cases: list[EnumerationCase], bypass_size_guard: bool = False) -> None:
    n = len(cases)
    if n > _COVERAGE_EXPLOSION_THRESHOLD and not bypass_size_guard:
        # Summarize breakdown for the operator so they can decide whether the
        # size is a real intent or a runaway axis.
        by_kind: dict[str, int] = {}
        for c in cases:
            by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
        breakdown = ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
        raise CoverageExplosionError(
            f"enumeration would produce {n} patients (threshold "
            f"{_COVERAGE_EXPLOSION_THRESHOLD}). Breakdown: {breakdown}. "
            f"If this is intentional, rerun with --yes-large."
        )


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass
class ManifestCase:
    patient_id: str
    kind: str
    scenario_id: str
    severity: str
    archetype: str
    country: str
    complication: str = ""  # populated only for disease complication-axis cases


@dataclass
class EnumerationManifest:
    schema_version: str = _MANIFEST_SCHEMA_VERSION
    clinosim_git_commit: str = ""
    level: str = "full"
    countries: list[str] = field(default_factory=list)
    base_seed: int = 0
    generated_at: str = ""
    total_patients: int = 0
    cases: list[ManifestCase] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def build_manifest(
    cases: list[EnumerationCase],
    patient_ids: list[str],
    level: EnumerationLevel,
    countries: list[str],
    base_seed: int,
    generated_at: str,
    git_commit: str = "",
) -> EnumerationManifest:
    """Build an EnumerationManifest given the expanded cases and their
    assigned patient_ids (parallel lists — same length, same order)."""
    if len(cases) != len(patient_ids):
        raise ValueError(f"cases and patient_ids length mismatch: {len(cases)} vs {len(patient_ids)}")
    manifest_cases = [
        ManifestCase(
            patient_id=pid,
            kind=c.kind,
            scenario_id=c.scenario_id,
            severity=c.severity,
            archetype=c.archetype,
            country=c.country,
            complication=c.complication,
        )
        for c, pid in zip(cases, patient_ids)
    ]
    return EnumerationManifest(
        schema_version=_MANIFEST_SCHEMA_VERSION,
        clinosim_git_commit=git_commit,
        level=level,
        countries=list(countries),
        base_seed=base_seed,
        generated_at=generated_at,
        total_patients=len(cases),
        cases=manifest_cases,
    )


def make_patient_id(index: int, case: EnumerationCase) -> str:
    """Produce a stable per-case patient_id.

    Prefix `ENUM-` marks the record as enumeration-generated (distinguishable
    from population `POP-` ids in downstream reports). Two-letter country
    code + zero-padded sequence keeps the id short and sortable while
    still being globally unique across the enumeration.
    """
    return f"ENUM-{case.country}-{index:04d}"


# ---------------------------------------------------------------------------
# Orchestrator entry point (used by CLI)
# ---------------------------------------------------------------------------


@dataclass
class EnumerationPlan:
    """Result of the plan phase — cases + manifest metadata, before actual
    simulation. Callers pass this to `run_enumeration` to execute."""

    cases: list[EnumerationCase]
    countries: list[str]
    level: EnumerationLevel
    base_seed: int


def plan_enumeration(
    level: EnumerationLevel = "full",
    countries: list[str] | None = None,
    base_seed: int = 42,
    bypass_size_guard: bool = False,
) -> EnumerationPlan:
    """Discover scenarios, expand cases at the requested level, run the
    coverage guard, and return the ready-to-execute plan."""
    if countries is None:
        countries = ["JP"]
    scenarios = discover_disease_scenarios() + discover_encounter_scenarios()
    cases: list[EnumerationCase] = []
    for country in countries:
        cases.extend(expand_cases(scenarios, level, country))
    check_coverage_size(cases, bypass_size_guard=bypass_size_guard)
    return EnumerationPlan(cases=cases, countries=countries, level=level, base_seed=base_seed)


def _resolve_git_commit() -> str:
    """Best-effort git commit lookup; empty string on failure (unit-test
    friendliness)."""
    try:
        import subprocess

        r = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip()[:12] if r.returncode == 0 else ""
    except Exception:
        return ""


def now_iso() -> str:
    """Wall-clock timestamp for manifest.generated_at. Kept as a module-level
    function so unit tests can monkeypatch it for deterministic golden
    comparisons if needed."""
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Execution — actually simulate the cases and assemble a CIFDataset
# ---------------------------------------------------------------------------


def run_enumeration(plan: EnumerationPlan) -> tuple[Any, EnumerationManifest]:
    """Simulate every case in the plan and return (CIFDataset, manifest).

    Each case gets a deterministic sub-seed via `derive_case_seed`.
    Disease cases use `run_forced(ForcedScenario)` (which already supports
    severity + archetype forcing). Encounter cases use the same code path
    as `test-encounter --output` (`_simulate_ed_visit`) with the new
    `force_severity` parameter.
    """
    # Imports are deferred so the enumerate module stays cheap to import for
    # discovery-only callers (tests that never simulate anything).
    from datetime import date
    from datetime import datetime as _dt

    import numpy as np

    from clinosim.locale.loader import load_demographics
    from clinosim.modules.encounter.protocol import load_encounter_condition
    from clinosim.modules.patient.activator import activate_patient
    from clinosim.modules.population.engine import PersonRecord
    from clinosim.modules.staff.engine import generate_roster
    from clinosim.simulator.emergency import _simulate_ed_visit
    from clinosim.simulator.engine import run_forced
    from clinosim.simulator.enrichers import register_builtin_enrichers
    from clinosim.types.config import ForcedScenario, SimulatorConfig
    from clinosim.types.output import CIFDataset, CIFMetadata

    register_builtin_enrichers()

    all_records: list[Any] = []
    patient_ids: list[str] = []

    for i, case in enumerate(plan.cases):
        pid = make_patient_id(i + 1, case)
        sub_seed = derive_case_seed(plan.base_seed, case)
        rng = np.random.default_rng(sub_seed)

        if case.kind == "disease":
            # Reuse the existing ForcedScenario / run_forced path — it already
            # accepts severity + archetype and produces a full simulation.
            # Complications: when the case carries a complication name, force
            # it via ForcedScenario.complications (consumed by engine.py:876
            # → record.complications_occurred). Empty complication = axis
            # not exercised, standard severity × archetype case.
            scenario = ForcedScenario(
                disease_id=case.scenario_id,
                count=1,
                severity=case.severity,
                archetype=case.archetype or None,
                complications=[case.complication] if case.complication else [],
            )
            config = SimulatorConfig(random_seed=int(sub_seed), country=case.country)
            dataset = run_forced(scenario, config=config)
            # run_forced generates FORCED-0001 as patient_id; overwrite so the
            # enumeration id (ENUM-JP-0001 etc.) is authoritative in the manifest.
            for rec in dataset.patients:
                rec.patient.patient_id = pid
                for enc in rec.encounters:
                    enc.patient_id = pid
            all_records.extend(dataset.patients)
        else:
            # Encounter path — mirror _run_test_encounter_generate but call the
            # ED-visit simulator directly with force_severity.
            _demo = load_demographics(case.country)
            roster = generate_roster("medium", case.country, rng)
            protocol = load_encounter_condition(case.scenario_id)
            age = int(rng.integers(30, 85))
            sex = str(rng.choice(["M", "F"]))
            # Issue #351 (session 63): populate family/given so the emitted
            # Patient.name carries non-empty strings on JP output. Without
            # this, the encounter-axis Patient resources emit
            # `family=""`, `given=[""]` with an iso21090 IDE representation
            # marker — a JP Core Patient profile violation. Matches the
            # same defaults `run_forced` sets on the disease path (which
            # is why disease-axis Patients were not affected).
            person = PersonRecord(
                person_id=pid,
                household_id=f"HH-{pid}",
                age=age,
                sex=sex,
                date_of_birth=date(2024 - age, 1, 1),
                family_name="テスト" if case.country == "JP" else "Test",
                given_name=f"患者{i + 1}" if case.country == "JP" else f"Patient{i + 1}",
            )
            patient = activate_patient(person, rng, _demo)
            visit_time = _dt(2024, 6, 15, int(rng.integers(8, 20)), int(rng.integers(0, 60)))
            config = SimulatorConfig(
                random_seed=int(sub_seed),
                country=case.country,
                catchment_population=1,
            )
            # Always pass force_severity — for encounters with an empty
            # severity_distribution ("routine" is the synthetic single-level
            # emitted by discover_encounter_scenarios), the simulator uses
            # the value as-is and its `ed_stay_hours[severity]` lookup falls
            # back to the default {mean: 3, sd: 1} entry, so any string is safe.
            record = _simulate_ed_visit(
                patient,
                protocol,
                visit_time,
                roster,
                rng,
                country=case.country,
                config=config,
                force_severity=case.severity,
            )
            record.patient.patient_id = pid
            for enc in record.encounters:
                enc.patient_id = pid
            all_records.append(record)

        patient_ids.append(pid)

    manifest = build_manifest(
        cases=plan.cases,
        patient_ids=patient_ids,
        level=plan.level,
        countries=plan.countries,
        base_seed=plan.base_seed,
        generated_at=now_iso(),
        git_commit=_resolve_git_commit(),
    )
    dataset = CIFDataset(
        metadata=CIFMetadata(
            random_seed=plan.base_seed,
            country=",".join(plan.countries),
            hospital_scale="medium",
            snapshot_date=_ENUMERATION_BASE_DATE,
            total_patients_generated=len(all_records),
        ),
        patients=all_records,
        hospital_roster=[],
        hospital_config={},
    )
    return dataset, manifest
