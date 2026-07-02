# α-min-2c Canonical Patient Profile Fixture Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a canonical patient profile fixture library (6 profiles + goldens) + `test-disease --patient-profile` CLI + `regenerate-goldens` CLI + `pytest -m regression` suite as the β-JP-1 LLMNarrativePass regression-testing foundation.

**Architecture:** New `PatientProfile` Pydantic type in `clinosim/types/config.py` transforms to existing `ForcedScenario` at CLI dispatch. Fixture YAMLs live in `tests/fixtures/patient_profiles/` alongside their `<name>.golden.json` template narrative expected output. Regression pytest suite subprocess-invokes `test-disease --patient-profile <id> --format cif -o <tmpdir>`, walks the resulting `cif/narratives/template/documents/**/*.json`, byte-diffs against golden.

**Tech Stack:** Python 3.11+ · Pydantic v2 (`>=2.6`) · pytest (marker `regression`) · ruff · mypy strict · YAML fixtures · JSON goldens.

## Global Constraints

(Copied verbatim from spec §10; every task implicitly includes these.)

- **CLAUDE.md AD-65 rules 1-5** preserved (narrative wrapper access, structural stubs, POST_SIMULATION pass, walk order, FHIR builder wrapper access)
- **CIF→FHIR no-drop invariant** applies — but α-min-2c does NOT emit new FHIR resources, so no matrix additions
- **AD-16 determinism**: profile fixtures use fixed seeds (default 42); golden regeneration must be byte-diff-stable at seed 42
- **Scope discipline**: 6 profiles only; no CI workflow; no clinical review loop; no semantic diff; no ED / outpatient encounter profiles — all deferred to TODO.md
- **Canonical single source**: fixture dir path constant `FIXTURE_DIR` defined ONCE in `tests/regression/conftest.py`, imported by test suite + `regenerate-goldens` CLI
- **PR-90 silent-no-op defense**: `PatientProfile` validates schema strictly (`model_config = {"extra": "forbid"}`), profile_id matches filename stem, disease_id exists in disease registry, RxNorm code lookup — all fail-loud at load time
- **Line length 100** (ruff), **English code comments**, **日本語 user-facing** where applicable
- **Frequent commits**: 1 commit per task at minimum, TDD red → green → refactor
- **Test invocation**: `pytest tests/unit -x -q` after each cluster; `pytest -m regression -q` for regression suite

---

## File Structure

**New files:**

- `tests/unit/test_patient_profile.py` — PatientProfile type + loader unit tests
- `tests/unit/test_cli_patient_profile.py` — `test-disease --patient-profile` CLI unit tests
- `tests/unit/test_cli_regenerate_goldens.py` — `regenerate-goldens` CLI unit tests
- `tests/fixtures/patient_profiles/README.md` — profile library documentation
- `tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.yaml`
- `tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.golden.json`
- `tests/fixtures/patient_profiles/us_inpatient_acute_mi.yaml`
- `tests/fixtures/patient_profiles/us_inpatient_acute_mi.golden.json`
- `tests/fixtures/patient_profiles/jp_icu_sepsis_hai_clabsi.yaml`
- `tests/fixtures/patient_profiles/jp_icu_sepsis_hai_clabsi.golden.json`
- `tests/fixtures/patient_profiles/us_inpatient_diabetic_ketoacidosis.yaml`
- `tests/fixtures/patient_profiles/us_inpatient_diabetic_ketoacidosis.golden.json`
- `tests/fixtures/patient_profiles/jp_inpatient_copd_exacerbation.yaml`
- `tests/fixtures/patient_profiles/jp_inpatient_copd_exacerbation.golden.json`
- `tests/fixtures/patient_profiles/us_inpatient_hemorrhagic_stroke.yaml`
- `tests/fixtures/patient_profiles/us_inpatient_hemorrhagic_stroke.golden.json`
- `tests/regression/__init__.py` — empty
- `tests/regression/conftest.py` — pytest marker registration + fixture path constants
- `tests/regression/test_narrative_profiles.py` — parametrized byte-diff regression suite

**Modified files:**

- `clinosim/types/config.py` — add `PatientProfile` class + `load_patient_profile()` function
- `clinosim/simulator/cli.py` — add `--patient-profile` flag to `test-disease` subcommand, add `regenerate-goldens` subcommand
- `docs/CONTRIBUTING-modules.md` — "Adding a new patient profile fixture" section
- `DESIGN.md` — AD-66 ADR appended
- `CLAUDE.md` — AD-66 rules 1-2 appended
- `TODO.md` — mark `Post-AD-65 fixture library` entry COMPLETED, add β-JP-1 semantic diff and ED/outpatient profiles as deferred entries

**Unchanged:** `MODULES.md` (fixture library is not a module).

---

## Task 1: `PatientProfile` type + loader

**Files:**
- Modify: `clinosim/types/config.py:66` (after existing `ForcedScenario` class)
- Create: `tests/unit/test_patient_profile.py`

**Interfaces:**
- Consumes: `ForcedScenario` (existing, unchanged), `code_lookup` from `clinosim.codes` (existing)
- Produces:
  - `class PatientProfile(BaseModel)` with fields listed in Step 3 code
  - `def load_patient_profile(name_or_path: str) -> PatientProfile` — resolves name via `tests/fixtures/patient_profiles/<name>.yaml`, or accepts absolute path directly
  - `PatientProfile.to_forced_scenario() -> ForcedScenario` method

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_patient_profile.py`:

```python
"""AD-66 α-min-2c: PatientProfile Pydantic type + loader tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from clinosim.types.config import (
    ForcedScenario,
    PatientProfile,
    load_patient_profile,
)


# --- Basic construction ---

def test_patient_profile_minimal_construction():
    """PatientProfile with only required fields works."""
    profile = PatientProfile(
        profile_id="test_minimal",
        disease_id="bacterial_pneumonia",
    )
    assert profile.profile_id == "test_minimal"
    assert profile.disease_id == "bacterial_pneumonia"
    assert profile.country == "US"  # default
    assert profile.severity is None
    assert profile.archetype is None
    assert profile.count == 1
    assert profile.random_seed == 42
    assert profile.hospital_scale == "medium"
    assert profile.patient_overrides == {}
    assert profile.force_hai_event is None
    assert profile.chronic_medications == []


def test_patient_profile_full_construction():
    """PatientProfile with all fields."""
    profile = PatientProfile(
        profile_id="full_test",
        disease_id="sepsis",
        country="JP",
        severity="severe",
        archetype="dip_then_recovery",
        count=1,
        random_seed=42,
        hospital_scale="large",
        patient_overrides={"age": 72, "sex": "M"},
        force_hai_event={
            "hai_type": "clabsi",
            "onset_offset_days": 3,
            "organism_snomed": "3092008",
        },
        chronic_medications=["6809"],  # metformin RxNorm code
        description="Full test profile",
        clinical_notes="Multi-line\nclinical notes",
    )
    assert profile.country == "JP"
    assert profile.force_hai_event["hai_type"] == "clabsi"
    assert profile.chronic_medications == ["6809"]


# --- Validation: extras forbidden ---

def test_patient_profile_rejects_unknown_keys():
    """Pydantic model_config = {'extra': 'forbid'} rejects typo'd YAML keys."""
    with pytest.raises(Exception) as exc_info:
        PatientProfile(
            profile_id="typo_test",
            disease_id="bacterial_pneumonia",
            typo_field="oops",  # unknown key
        )
    # Pydantic v2 raises ValidationError; be liberal on match
    assert "typo_field" in str(exc_info.value) or "extra" in str(exc_info.value).lower()


# --- Validation: country enum ---

def test_patient_profile_rejects_unknown_country():
    """Only US and JP are accepted."""
    with pytest.raises(Exception):
        PatientProfile(
            profile_id="bad_country",
            disease_id="bacterial_pneumonia",
            country="FR",
        )


# --- Validation: severity enum ---

def test_patient_profile_severity_none_is_valid():
    profile = PatientProfile(
        profile_id="sev_none",
        disease_id="bacterial_pneumonia",
        severity=None,
    )
    assert profile.severity is None


def test_patient_profile_severity_mild_moderate_severe():
    for sev in ("mild", "moderate", "severe"):
        profile = PatientProfile(
            profile_id=f"sev_{sev}",
            disease_id="bacterial_pneumonia",
            severity=sev,
        )
        assert profile.severity == sev


def test_patient_profile_rejects_unknown_severity():
    with pytest.raises(Exception):
        PatientProfile(
            profile_id="bad_sev",
            disease_id="bacterial_pneumonia",
            severity="critical",  # not in enum
        )


# --- to_forced_scenario transform ---

def test_to_forced_scenario_round_trips_relevant_fields():
    """PatientProfile.to_forced_scenario() preserves all ForcedScenario-relevant fields."""
    profile = PatientProfile(
        profile_id="fs_transform",
        disease_id="sepsis",
        severity="severe",
        archetype="dip_then_recovery",
        count=1,
        patient_overrides={"age": 65},
        force_hai_event={
            "hai_type": "clabsi",
            "onset_offset_days": 3,
            "organism_snomed": "3092008",
        },
    )
    scenario = profile.to_forced_scenario()
    assert isinstance(scenario, ForcedScenario)
    assert scenario.disease_id == "sepsis"
    assert scenario.severity == "severe"
    assert scenario.archetype == "dip_then_recovery"
    assert scenario.count == 1
    assert scenario.patient_overrides == {"age": 65}
    assert scenario.force_hai_event["hai_type"] == "clabsi"


# --- Loader: by name (default fixture dir) ---

def test_load_patient_profile_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_patient_profile('name') resolves via fixtures directory."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    yaml_path = fixture_dir / "test_by_name.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "profile_id": "test_by_name",
        "disease_id": "bacterial_pneumonia",
        "country": "JP",
        "severity": "moderate",
    }))

    # Override the fixture dir lookup for this test
    from clinosim.types import config as config_module
    monkeypatch.setattr(config_module, "_PATIENT_PROFILE_DIR", fixture_dir)

    profile = load_patient_profile("test_by_name")
    assert profile.profile_id == "test_by_name"
    assert profile.country == "JP"


# --- Loader: by absolute path ---

def test_load_patient_profile_by_path(tmp_path: Path):
    """load_patient_profile('/abs/path.yaml') loads the file directly."""
    yaml_path = tmp_path / "custom_location.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "profile_id": "custom_location",
        "disease_id": "sepsis",
    }))

    profile = load_patient_profile(str(yaml_path))
    assert profile.profile_id == "custom_location"
    assert profile.disease_id == "sepsis"


# --- Loader: profile_id / filename mismatch = raise ---

def test_load_patient_profile_id_filename_mismatch_raises(tmp_path: Path):
    """profile_id in YAML must match filename stem (silent-no-op defense)."""
    yaml_path = tmp_path / "actual_name.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "profile_id": "different_name",  # mismatch
        "disease_id": "bacterial_pneumonia",
    }))

    with pytest.raises(ValueError, match="profile_id"):
        load_patient_profile(str(yaml_path))


# --- Loader: file not found ---

def test_load_patient_profile_missing_file_raises():
    """load_patient_profile with unknown name raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_patient_profile("nonexistent_profile_id_12345")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_patient_profile.py -x -q`

Expected: FAIL — `PatientProfile` and `load_patient_profile` don't exist yet.

- [ ] **Step 3: Add `PatientProfile` class and loader to `clinosim/types/config.py`**

Read `clinosim/types/config.py` first. Then insert the following AFTER the `ForcedScenario` class (around line 82):

```python
# --- α-min-2c: Canonical Patient Profile fixture library (AD-66) ---

_PATIENT_PROFILE_DIR: Path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "patient_profiles"


class PatientProfile(BaseModel):
    """Canonical patient scenario fixture for narrative regression testing (α-min-2c, AD-66).

    Loaded from tests/fixtures/patient_profiles/<name>.yaml. Transformed to
    ForcedScenario at CLI dispatch via .to_forced_scenario(). β-JP-1 extends
    with LLM-specific fields (llm_seed, expected_sections, ...).
    """

    model_config = {"extra": "forbid"}

    # --- Identity ---
    profile_id: str

    # --- Simulation inputs ---
    disease_id: str
    country: Literal["US", "JP"] = "US"
    severity: Literal["mild", "moderate", "severe"] | None = None
    archetype: str | None = None
    count: int = 1
    random_seed: int = 42
    hospital_scale: Literal["small", "medium", "large"] = "medium"

    # --- Optional overrides ---
    patient_overrides: dict = {}
    force_hai_event: dict | None = None
    chronic_medications: list[str] = []
    time_range: tuple[str, str] = ("2024-04-01", "2025-03-31")

    # --- Documentation ---
    description: str = ""
    clinical_notes: str = ""

    def to_forced_scenario(self) -> ForcedScenario:
        return ForcedScenario(
            disease_id=self.disease_id,
            count=self.count,
            severity=self.severity,
            archetype=self.archetype,
            patient_overrides=self.patient_overrides,
            force_hai_event=self.force_hai_event,
        )


def load_patient_profile(name_or_path: str) -> PatientProfile:
    """Resolve a patient profile by name or absolute path.

    - If ``name_or_path`` exists as a file → load directly.
    - Otherwise → resolve as ``tests/fixtures/patient_profiles/<name>.yaml``.

    Raises:
        FileNotFoundError: unresolvable name / missing file
        pydantic.ValidationError: schema mismatch (extra keys, wrong types, etc.)
        ValueError: profile_id does not match filename stem
    """
    import yaml

    p = Path(name_or_path)
    if not p.is_file():
        p = _PATIENT_PROFILE_DIR / f"{name_or_path}.yaml"
        if not p.is_file():
            raise FileNotFoundError(
                f"patient profile not found: {name_or_path!r} "
                f"(looked in {_PATIENT_PROFILE_DIR} and as literal path)"
            )

    data = yaml.safe_load(p.read_text())
    profile = PatientProfile(**data)

    expected_stem = p.stem
    if profile.profile_id != expected_stem:
        raise ValueError(
            f"profile_id {profile.profile_id!r} does not match filename stem "
            f"{expected_stem!r} in {p} (silent-no-op defense)"
        )

    return profile
```

Add imports at the top of the file if not already present:
```python
from pathlib import Path
from typing import Literal
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_patient_profile.py -x -q`

Expected: 11 tests PASS.

- [ ] **Step 5: Verify no unit regressions**

Run: `pytest tests/unit -x -q -k "not narrative_pass_walk and not narrative_pass_determinism"` (exclude tests that might load real profile fixtures which don't exist yet)

Expected: 0 failures.

Then full unit: `pytest tests/unit -x -q`

Expected: 0 failures.

- [ ] **Step 6: Commit**

```bash
git add clinosim/types/config.py tests/unit/test_patient_profile.py
git commit -m "$(cat <<'EOF'
feat(types): PatientProfile Pydantic + load_patient_profile (α-min-2c T1)

New PatientProfile type in clinosim/types/config.py:
- Pydantic v2 with extra='forbid' (schema drift defense)
- Literal-typed country / severity / hospital_scale enums
- .to_forced_scenario() transforms to existing ForcedScenario
- Reserved fields for β-JP-1 LLM-specific extensions

New load_patient_profile(name_or_path) loader:
- Resolves name via tests/fixtures/patient_profiles/<name>.yaml
- Accepts absolute path directly
- Fails loud on schema violations + profile_id/filename mismatch
  (silent-no-op defense per PR-90 lesson)

11 unit tests cover: minimal + full construction, extras rejection,
enum validation, .to_forced_scenario round-trip, by-name loader,
by-path loader, profile_id/filename mismatch raise, missing file raise.

AD-66 (canonical patient profile fixture library) foundation type.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `test-disease --patient-profile` CLI wiring

**Files:**
- Modify: `clinosim/simulator/cli.py:74-96` (test-disease subparser) + `clinosim/simulator/cli.py:_run_test_disease_generate`
- Create: `tests/unit/test_cli_patient_profile.py`

**Interfaces:**
- Consumes: `PatientProfile`, `load_patient_profile` from Task 1
- Produces: `test-disease --patient-profile <name-or-path>` CLI flag; when set, dispatches through profile → ForcedScenario → run_forced pipeline

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_cli_patient_profile.py`:

```python
"""AD-66 α-min-2c T2: test-disease --patient-profile CLI wiring tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _write_profile(tmp_path: Path, name: str, data: dict) -> Path:
    """Helper: write a YAML profile file under tmp_path."""
    yaml_path = tmp_path / f"{name}.yaml"
    yaml_path.write_text(yaml.safe_dump(data))
    return yaml_path


# --- Argparse: --patient-profile flag exists ---

def test_test_disease_help_mentions_patient_profile():
    """`clinosim test-disease --help` includes --patient-profile."""
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert "--patient-profile" in result.stdout


# --- Positional disease_id is optional when --patient-profile given ---

def test_positional_disease_id_optional_with_profile(tmp_path: Path):
    """`test-disease --patient-profile PATH -o OUT` works without positional disease_id."""
    profile_path = _write_profile(tmp_path, "smoke_test", {
        "profile_id": "smoke_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "--patient-profile", str(profile_path),
         "--format", "cif", "-o", str(out_dir)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    # Verify CIF structural output exists
    assert (out_dir / "cif" / "structural" / "patients").is_dir()


# --- CLI arg overrides profile (Bug D lesson: explicit CLI wins) ---

def test_cli_severity_overrides_profile_with_warn(tmp_path: Path):
    """When --severity differs from profile.severity, CLI wins + stderr warns."""
    profile_path = _write_profile(tmp_path, "override_test", {
        "profile_id": "override_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "mild",
        "count": 1,
        "random_seed": 42,
    })
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "--patient-profile", str(profile_path),
         "--severity", "severe",  # override
         "--format", "cif", "-o", str(out_dir)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "WARN" in result.stderr or "warn" in result.stderr.lower()
    assert "severity" in result.stderr.lower()


# --- Positional disease_id overrides profile.disease_id with warn ---

def test_positional_disease_id_overrides_profile_with_warn(tmp_path: Path):
    """When positional differs from profile.disease_id, positional wins + warn."""
    profile_path = _write_profile(tmp_path, "disease_override", {
        "profile_id": "disease_override",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "sepsis",  # positional override
         "--patient-profile", str(profile_path),
         "--format", "cif", "-o", str(out_dir)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "WARN" in result.stderr or "warn" in result.stderr.lower()
    assert "disease" in result.stderr.lower()


# --- Missing profile → exit 2 with actionable message ---

def test_missing_profile_exits_2_with_message(tmp_path: Path):
    """--patient-profile nonexistent → sys.exit(2) with actionable error."""
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "--patient-profile", "nonexistent_profile_xyz",
         "--format", "cif", "-o", str(out_dir)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2, f"expected exit 2, got {result.returncode}"
    assert "nonexistent_profile_xyz" in result.stderr or "not found" in result.stderr.lower()


# --- Determinism: same profile + seed → same CIF ---

def test_same_profile_produces_deterministic_cif(tmp_path: Path):
    """Two runs with the same profile + seed produce byte-identical CIF."""
    profile_path = _write_profile(tmp_path, "determinism_test", {
        "profile_id": "determinism_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    for out in (out1, out2):
        subprocess.run(
            [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
             "--patient-profile", str(profile_path),
             "--format", "cif", "-o", str(out)],
            capture_output=True, text=True, check=True,
        )
    # Compare structural CIF files
    files1 = sorted((out1 / "cif" / "structural" / "patients").iterdir())
    files2 = sorted((out2 / "cif" / "structural" / "patients").iterdir())
    assert len(files1) == len(files2) and len(files1) > 0
    for f1, f2 in zip(files1, files2):
        assert f1.read_text() == f2.read_text(), f"CIF diverged for {f1.name}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_cli_patient_profile.py -x -q`

Expected: FAIL — `--patient-profile` flag not wired.

- [ ] **Step 3: Add `--patient-profile` flag to `test-disease` subparser**

Read `clinosim/simulator/cli.py` lines around 74-96 (test-disease subparser). Find the section that looks like:
```python
td = sub.add_parser("test-disease", help="Generate data for a specific disease and archetype")
td.add_argument("disease_id", help="Disease ID (e.g., bacterial_pneumonia)")
```

Modify to make `disease_id` optional (`nargs='?'`) and add `--patient-profile`:
```python
td = sub.add_parser("test-disease", help="Generate data for a specific disease and archetype")
td.add_argument("disease_id", nargs="?", default=None,
                help="Disease ID (e.g., bacterial_pneumonia); optional when --patient-profile is set")
td.add_argument("--patient-profile", default=None,
                help="Patient profile fixture name or path (AD-66); overrides disease_id when both given")
```

- [ ] **Step 4: Add profile dispatch to `_run_test_disease_generate`**

Read `_run_test_disease_generate` in `clinosim/simulator/cli.py`. Find the section constructing `ForcedScenario`:
```python
scenario = ForcedScenario(
    disease_id=args.disease_id,
    count=args.count,
    severity=args.severity,
    archetype=args.archetype,
    ...
)
```

Wrap with profile handling. Add BEFORE the existing scenario construction:

```python
# AD-66 α-min-2c: --patient-profile support
from clinosim.types.config import load_patient_profile, PatientProfile

profile: PatientProfile | None = None
if args.patient_profile:
    profile = load_patient_profile(args.patient_profile)

    # CLI arg overrides profile (Bug D lesson: explicit CLI > implicit YAML)
    if args.disease_id and args.disease_id != profile.disease_id:
        print(
            f"WARN: positional disease_id={args.disease_id!r} differs from "
            f"--patient-profile disease_id={profile.disease_id!r}; using positional",
            file=sys.stderr,
        )
        profile = profile.model_copy(update={"disease_id": args.disease_id})
    if args.severity is not None and args.severity != profile.severity:
        print(
            f"WARN: --severity={args.severity!r} differs from profile severity="
            f"{profile.severity!r}; using --severity",
            file=sys.stderr,
        )
        profile = profile.model_copy(update={"severity": args.severity})
    if args.archetype is not None and args.archetype != profile.archetype:
        print(
            f"WARN: --archetype={args.archetype!r} differs from profile archetype="
            f"{profile.archetype!r}; using --archetype",
            file=sys.stderr,
        )
        profile = profile.model_copy(update={"archetype": args.archetype})
    if args.seed != 42 and args.seed != profile.random_seed:
        # only warn if user explicitly changed seed from default AND it differs
        print(
            f"WARN: --seed={args.seed} differs from profile random_seed={profile.random_seed}; "
            f"using --seed",
            file=sys.stderr,
        )
        profile = profile.model_copy(update={"random_seed": args.seed})
    if args.country != "US" and args.country != profile.country:
        # only warn if user explicitly changed country from default AND it differs
        print(
            f"WARN: --country={args.country!r} differs from profile country="
            f"{profile.country!r}; using --country",
            file=sys.stderr,
        )
        profile = profile.model_copy(update={"country": args.country})

    scenario = profile.to_forced_scenario()
    config = SimulatorConfig(
        random_seed=profile.random_seed,
        country=profile.country,
        hospital_scale=profile.hospital_scale,
    )
else:
    if not args.disease_id:
        print(
            "ERROR: either positional disease_id or --patient-profile must be provided",
            file=sys.stderr,
        )
        sys.exit(2)
    scenario = ForcedScenario(
        disease_id=args.disease_id,
        count=args.count,
        severity=args.severity,
        archetype=args.archetype,
    )
    config = SimulatorConfig(country=args.country, random_seed=args.seed)
```

Then remove or comment out the old `scenario = ForcedScenario(...)` block that follows (it's now in the `else` branch).

Add error path for load_patient_profile failure — wrap `load_patient_profile` call:
```python
try:
    profile = load_patient_profile(args.patient_profile)
except FileNotFoundError as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(2)
except Exception as e:  # Pydantic ValidationError or ValueError
    print(f"ERROR: invalid patient profile: {e}", file=sys.stderr)
    sys.exit(2)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_cli_patient_profile.py -x -q`

Expected: 6 tests PASS.

- [ ] **Step 6: Verify no unit regressions**

Run: `pytest tests/unit -x -q`

Expected: 0 failures.

- [ ] **Step 7: Commit**

```bash
git add clinosim/simulator/cli.py tests/unit/test_cli_patient_profile.py
git commit -m "feat(cli): test-disease --patient-profile flag (α-min-2c T2)

Wire --patient-profile flag into test-disease subcommand:
- positional disease_id now optional (nargs='?')
- --patient-profile <name-or-path> loads via load_patient_profile
- CLI args override profile with stderr WARN (Bug D lesson)
- Missing profile → exit 2 with actionable message
- Missing both disease_id and --patient-profile → exit 2

6 subprocess-invocation unit tests cover: help output includes flag,
positional optional with profile, CLI severity/disease_id override,
missing profile exit 2, determinism (2 runs = byte-identical CIF).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `regenerate-goldens` CLI subcommand

**Files:**
- Modify: `clinosim/simulator/cli.py` (add `regenerate-goldens` subparser + dispatch)
- Create: `tests/unit/test_cli_regenerate_goldens.py`

**Interfaces:**
- Consumes: `load_patient_profile` (Task 1), `test-disease --patient-profile` dispatch (Task 2)
- Produces:
  - `clinosim regenerate-goldens [--profile <name> | --all]` CLI subcommand
  - When invoked, runs the pipeline for each profile, walks generated narratives, writes `<profile>.golden.json`

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_cli_regenerate_goldens.py`:

```python
"""AD-66 α-min-2c T3: regenerate-goldens CLI unit tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _write_profile(fixture_dir: Path, name: str, data: dict) -> Path:
    yaml_path = fixture_dir / f"{name}.yaml"
    yaml_path.write_text(yaml.safe_dump(data))
    return yaml_path


# --- --help mentions the subcommand ---

def test_regenerate_goldens_help():
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "--profile" in result.stdout
    assert "--all" in result.stdout


# --- --profile <name> regenerates a single golden ---

def test_regenerate_single_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    _write_profile(fixture_dir, "single_test", {
        "profile_id": "single_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })

    monkeypatch.setenv("CLINOSIM_PATIENT_PROFILE_DIR", str(fixture_dir))
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "single_test"],
        capture_output=True, text=True, check=False,
        env={**dict(__import__("os").environ), "CLINOSIM_PATIENT_PROFILE_DIR": str(fixture_dir)},
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    golden_path = fixture_dir / "single_test.golden.json"
    assert golden_path.is_file(), "golden JSON not written"
    golden = json.loads(golden_path.read_text())
    assert isinstance(golden, dict), "golden should be document_id → narrative_dict"


# --- --all regenerates all fixtures in the dir ---

def test_regenerate_all_profiles(tmp_path: Path):
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    for name in ("all_test_a", "all_test_b"):
        _write_profile(fixture_dir, name, {
            "profile_id": name,
            "disease_id": "bacterial_pneumonia",
            "country": "US",
            "severity": "moderate",
            "count": 1,
            "random_seed": 42,
        })

    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens", "--all"],
        capture_output=True, text=True, check=False,
        env={**dict(__import__("os").environ), "CLINOSIM_PATIENT_PROFILE_DIR": str(fixture_dir)},
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert (fixture_dir / "all_test_a.golden.json").is_file()
    assert (fixture_dir / "all_test_b.golden.json").is_file()


# --- --profile and --all mutually exclusive ---

def test_profile_and_all_mutually_exclusive(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "x", "--all"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "mutually" in result.stderr.lower() or "not allowed" in result.stderr.lower()


# --- Idempotency: running twice = zero diff ---

def test_regenerate_is_idempotent(tmp_path: Path):
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    _write_profile(fixture_dir, "idem_test", {
        "profile_id": "idem_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })
    env = {**dict(__import__("os").environ), "CLINOSIM_PATIENT_PROFILE_DIR": str(fixture_dir)}

    subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "idem_test"],
        env=env, capture_output=True, text=True, check=True,
    )
    first = (fixture_dir / "idem_test.golden.json").read_text()

    subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "idem_test"],
        env=env, capture_output=True, text=True, check=True,
    )
    second = (fixture_dir / "idem_test.golden.json").read_text()

    assert first == second, "regenerate-goldens is not idempotent (byte-diff between two runs)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_cli_regenerate_goldens.py -x -q`

Expected: FAIL — subcommand not wired.

- [ ] **Step 3: Add `regenerate-goldens` subparser + dispatch**

Add to `clinosim/simulator/cli.py` in the subparsers section (near other sub.add_parser calls):

```python
# === regenerate-goldens: AD-66 α-min-2c golden narrative bootstrap ===
rg = sub.add_parser(
    "regenerate-goldens",
    help="Regenerate narrative goldens for canonical patient profiles (AD-66)",
)
rg_group = rg.add_mutually_exclusive_group(required=True)
rg_group.add_argument(
    "--profile", default=None,
    help="Regenerate a single profile by name",
)
rg_group.add_argument(
    "--all", action="store_true",
    help="Regenerate goldens for all profiles in the fixtures dir",
)
```

Add dispatch in the main function's if-elif chain:

```python
if args.command == "regenerate-goldens":
    _run_regenerate_goldens(args)
    return
```

Add the implementation function:

```python
def _run_regenerate_goldens(args: Any) -> None:
    """AD-66 α-min-2c T3: regenerate narrative goldens for canonical profiles.

    For each target profile: run test-disease pipeline into a tmpdir, walk
    cif/narratives/template/documents/**/*.json, write the merged dict to
    <profile>.golden.json in the fixture dir. Emits stderr note prompting
    user to `git diff + commit if intentional`.
    """
    import os
    import tempfile
    from clinosim.types.config import _PATIENT_PROFILE_DIR

    # Support env var override for test isolation
    fixture_dir_env = os.environ.get("CLINOSIM_PATIENT_PROFILE_DIR")
    fixture_dir = Path(fixture_dir_env) if fixture_dir_env else _PATIENT_PROFILE_DIR

    if args.all:
        profile_paths = sorted(fixture_dir.glob("*.yaml"))
    else:
        p = fixture_dir / f"{args.profile}.yaml"
        if not p.is_file():
            print(f"ERROR: profile not found: {p}", file=sys.stderr)
            sys.exit(2)
        profile_paths = [p]

    if not profile_paths:
        print(f"ERROR: no profiles found in {fixture_dir}", file=sys.stderr)
        sys.exit(2)

    count = 0
    for profile_path in profile_paths:
        profile_id = profile_path.stem
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
                 "--patient-profile", str(profile_path),
                 "--format", "cif", "-o", str(tmpdir)],
                check=True, capture_output=True, text=True,
            )
            narr_dir = Path(tmpdir) / "cif" / "narratives" / "template" / "documents"
            actual: dict[str, dict] = {}
            if narr_dir.is_dir():
                for enc_dir in sorted(narr_dir.iterdir()):
                    if not enc_dir.is_dir():
                        continue
                    for doc_file in sorted(enc_dir.iterdir()):
                        if doc_file.suffix != ".json":
                            continue
                        actual[doc_file.stem] = json.loads(doc_file.read_text())

            golden_path = fixture_dir / f"{profile_id}.golden.json"
            golden_path.write_text(
                json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            )
            count += 1
            print(f"regenerated: {golden_path}", file=sys.stderr)

    print(
        f"Regenerated {count} golden(s). Review + git diff + commit if intentional.",
        file=sys.stderr,
    )
```

Add imports at the top of cli.py if not present:
```python
import json
import subprocess
from pathlib import Path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_cli_regenerate_goldens.py -x -q`

Expected: 5 tests PASS.

- [ ] **Step 5: Verify no unit regressions**

Run: `pytest tests/unit -x -q`

Expected: 0 failures.

- [ ] **Step 6: Commit**

```bash
git add clinosim/simulator/cli.py tests/unit/test_cli_regenerate_goldens.py
git commit -m "feat(cli): regenerate-goldens subcommand (α-min-2c T3)

New clinosim regenerate-goldens [--profile <name> | --all] subcommand:
- Subprocess-invokes test-disease pipeline per profile
- Walks cif/narratives/template/documents/**/*.json
- Writes to <profile>.golden.json (sort_keys, ensure_ascii=False)
- Idempotent (2 runs = byte-identical output)
- --profile and --all are mutually exclusive
- CLINOSIM_PATIENT_PROFILE_DIR env var for test isolation

5 subprocess unit tests cover: help output, single-profile mode,
--all mode, mutual exclusion, idempotency.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `tests/fixtures/patient_profiles/README.md` + fixture dir bootstrap

**Files:**
- Create: `tests/fixtures/patient_profiles/README.md`

**Interfaces:** documentation only, no code interfaces.

- [ ] **Step 1: Create the fixture directory**

```bash
mkdir -p tests/fixtures/patient_profiles
```

- [ ] **Step 2: Write README.md**

Create `tests/fixtures/patient_profiles/README.md`:

```markdown
# Canonical Patient Profile Fixture Library (α-min-2c, AD-66)

Deterministic patient scenario fixtures used by the narrative regression suite
(`tests/regression/test_narrative_profiles.py`). Each profile ships as a pair:

- `<profile_id>.yaml` — input (PatientProfile schema; see
  `clinosim/types/config.py:PatientProfile`)
- `<profile_id>.golden.json` — expected template narrative output for that
  profile at seed 42

This library is the β-JP-1 blocker: it establishes a deterministic
baseline against which future `LLMNarrativePass` output can be regression-tested.

## Profiles (α-min-2c ships 6)

| Profile ID | Disease | Severity | Archetype | Country |
|---|---|---|---|---|
| `jp_inpatient_bacterial_pneumonia` | bacterial_pneumonia | moderate | smooth_recovery | JP |
| `us_inpatient_acute_mi` | acute_mi | severe | plateau | US |
| `jp_icu_sepsis_hai_clabsi` | sepsis (+HAI) | severe | dip_then_recovery | JP |
| `us_inpatient_diabetic_ketoacidosis` | diabetic_ketoacidosis | severe | smooth_recovery | US |
| `jp_inpatient_copd_exacerbation` | copd_exacerbation | moderate | dip_then_recovery | JP |
| `us_inpatient_hemorrhagic_stroke` | hemorrhagic_stroke | severe | dip_then_recovery | US |

## Naming convention

`<country>_<encounter_type>_<condition_slug>.yaml`
- `country`: `us` / `jp`
- `encounter_type`: `inpatient` / `icu` (α-min-2c) / `ed` / `outpatient` (deferred to β-JP-1+)
- `condition_slug`: disease_id verbatim

## Adding a new profile

1. Copy the closest existing `<profile>.yaml`, edit fields
2. Ensure `profile_id` matches the new filename stem (loader raises otherwise)
3. Verify `disease_id` exists in `clinosim/modules/disease/reference_data/` and the chosen `archetype` exists in that disease's `course_archetypes`
4. Generate the initial golden:
   ```bash
   clinosim regenerate-goldens --profile <new_profile_id>
   ```
5. Manually review `<new_profile_id>.golden.json` — does it look right?
6. Commit both files together (see AD-66 rule 1: YAML changes must ship with golden regeneration)
7. Run the regression suite to verify:
   ```bash
   pytest -m regression -k <new_profile_id> -q
   ```

## Regenerating goldens after intentional narrative changes

When you intentionally change template narrative logic (e.g., add a new
section to the H&P template), the goldens will diff. Workflow:

1. Make the narrative change
2. Regenerate all goldens: `clinosim regenerate-goldens --all`
3. `git diff tests/fixtures/patient_profiles/*.golden.json` — inspect the diff
4. **Unexpected diff = regression suspicion**. Revert or fix the implementation.
5. **Expected diff** = commit YAML + golden together in the same PR.

See `CLAUDE.md` AD-66 rules 1-2 for the canonical policy.

## Regression suite invocation

```bash
# Run all profile regressions
pytest -m regression -q

# Run a single profile
pytest -m regression -k jp_inpatient_bacterial_pneumonia -q

# Verbose diff output on failure
pytest -m regression -q -s
```

The regression suite is opt-in via marker; the default `pytest` run does not
execute it (LLM cost + subprocess latency budget considerations).

## Related

- Spec: `docs/superpowers/specs/2026-07-03-tier1-3-alpha-min-2c-fixture-library-design.md`
- ADR: `DESIGN.md` AD-66
- CLAUDE.md AD-66 rules
```

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/patient_profiles/README.md
git commit -m "docs(fixtures): AD-66 patient profile library README (α-min-2c T4)

Documentation-only commit. tests/fixtures/patient_profiles/ established
as the canonical directory for β-JP-1 narrative regression fixtures.

README covers: profile inventory (6 α-min-2c profiles), naming
convention, add-a-profile workflow, golden regeneration policy,
regression suite invocation.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Profile #1 — `jp_inpatient_bacterial_pneumonia`

**Files:**
- Create: `tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.yaml`
- Create: `tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.golden.json` (via regenerate-goldens)

**Interfaces:** consumes T1-T3 (types, CLI, regenerate). No new code interfaces.

- [ ] **Step 1: Verify archetype exists in disease YAML**

```bash
grep -A 20 "^course_archetypes:" clinosim/modules/disease/reference_data/bacterial_pneumonia.yaml | grep -E "^  [a-z_]+:"
```

Expected output includes `smooth_recovery:`. If not, adjust archetype below.

- [ ] **Step 2: Write the profile YAML**

Create `tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.yaml`:

```yaml
# AD-66 canonical patient profile fixture — α-min-2c
profile_id: jp_inpatient_bacterial_pneumonia
disease_id: bacterial_pneumonia
country: JP
severity: moderate
archetype: smooth_recovery
count: 1
random_seed: 42
hospital_scale: medium

patient_overrides:
  age: 68
  sex: F

description: |
  Community-acquired bacterial pneumonia in an elderly JP patient with
  smooth recovery trajectory. Multi-day inpatient admission with
  admission H&P, daily progress notes, and discharge summary.
  β-JP-1 target: JP linguistic narrative expression for common
  inpatient pneumonia case.
clinical_notes: |
  Chest X-ray: RLL consolidation
  Sputum culture: Streptococcus pneumoniae
  Empirical antibiotic: ceftriaxone
```

- [ ] **Step 3: Generate the golden**

```bash
clinosim regenerate-goldens --profile jp_inpatient_bacterial_pneumonia
```

Expected: `tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.golden.json` created; stderr shows `regenerated: ...` and `Regenerated 1 golden(s)...`.

- [ ] **Step 4: Manually sanity-check the golden**

```bash
python -c "
import json
g = json.load(open('tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.golden.json'))
print('Number of documents:', len(g))
print('Document IDs:', sorted(g.keys())[:5])
first_doc = next(iter(g.values()))
print('Sample doc fields:', list(first_doc.keys()))
if 'sections' in first_doc:
    print('Sample section keys:', list(first_doc['sections'].keys())[:5])
"
```

Expected: multiple documents (admission H&P + progress notes + discharge summary), each with `text`, `sections`, `generator: "template"`, etc.

- [ ] **Step 5: Confirm determinism (regenerate twice = zero diff)**

```bash
clinosim regenerate-goldens --profile jp_inpatient_bacterial_pneumonia
git diff tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.golden.json
```

Expected: no diff. If diff present, investigate nondeterminism — likely something in the narrative pass is not seed-derived.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.yaml \
        tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.golden.json
git commit -m "fixture(profiles): jp_inpatient_bacterial_pneumonia (α-min-2c T5)

Profile #1: JP CAP moderate severity smooth-recovery inpatient.
Elderly (age 68 F) community-acquired pneumonia, multi-day LOS with
admission H&P + progress notes + discharge summary.

Deterministic at seed 42. β-JP-1 target: JP linguistic H&P narrative.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Profile #2 — `us_inpatient_acute_mi`

**Files:**
- Create: `tests/fixtures/patient_profiles/us_inpatient_acute_mi.yaml`
- Create: `tests/fixtures/patient_profiles/us_inpatient_acute_mi.golden.json`

**Interfaces:** consumes T1-T3. No new interfaces.

- [ ] **Step 1: Verify archetype `plateau` in `acute_mi`**

```bash
grep -A 20 "^course_archetypes:" clinosim/modules/disease/reference_data/acute_mi.yaml | grep -E "^  [a-z_]+:"
```

Expected includes `plateau:`. If not, fall back to `dip_then_recovery`.

- [ ] **Step 2: Write the profile YAML**

Create `tests/fixtures/patient_profiles/us_inpatient_acute_mi.yaml`:

```yaml
profile_id: us_inpatient_acute_mi
disease_id: acute_mi
country: US
severity: severe
archetype: plateau
count: 1
random_seed: 42
hospital_scale: medium

patient_overrides:
  age: 62
  sex: M

description: |
  Severe acute MI in a middle-aged US male, plateau trajectory
  (delayed recovery, sustained cardiac dysfunction). Multi-day
  inpatient admission with troponin trajectory, PCI procedure
  documentation, and complex discharge planning.
  β-JP-1 target: US H&P + procedure documentation + discharge summary.
clinical_notes: |
  ECG: STEMI (anterior)
  Troponin rise-and-fall pattern expected
  Coronary angiography + PCI
  Post-procedure: dual antiplatelet therapy
```

- [ ] **Step 3: Generate the golden**

```bash
clinosim regenerate-goldens --profile us_inpatient_acute_mi
```

- [ ] **Step 4: Sanity check**

```bash
python -c "
import json
g = json.load(open('tests/fixtures/patient_profiles/us_inpatient_acute_mi.golden.json'))
print('Documents:', len(g))
print('IDs:', sorted(g.keys())[:5])
"
```

- [ ] **Step 5: Determinism check**

```bash
clinosim regenerate-goldens --profile us_inpatient_acute_mi
git diff tests/fixtures/patient_profiles/us_inpatient_acute_mi.golden.json
```

Expected: no diff.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/patient_profiles/us_inpatient_acute_mi.yaml \
        tests/fixtures/patient_profiles/us_inpatient_acute_mi.golden.json
git commit -m "fixture(profiles): us_inpatient_acute_mi (α-min-2c T6)

Profile #2: US STEMI severe plateau-trajectory inpatient.
Middle-aged male (age 62) with anterior STEMI, PCI, and post-procedure
management. Multi-day LOS with troponin trajectory + procedure doc.

Deterministic at seed 42. β-JP-1 target: US H&P + procedure narrative.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Profile #3 — `jp_icu_sepsis_hai_clabsi` (with HAI force)

**Files:**
- Create: `tests/fixtures/patient_profiles/jp_icu_sepsis_hai_clabsi.yaml`
- Create: `tests/fixtures/patient_profiles/jp_icu_sepsis_hai_clabsi.golden.json`

**Interfaces:** consumes T1-T3 + existing `force_hai_event` machinery in `run_forced` (`clinosim/simulator/engine.py`).

- [ ] **Step 1: Verify HAI organism SNOMED**

```bash
grep -A 20 "^  clabsi:" clinosim/modules/hai/reference_data/hai_organisms.yaml
```

Expected: `3092008` (S. aureus) present in the CLABSI list. If not, substitute with a canonical CLABSI SNOMED from the file.

- [ ] **Step 2: Verify `sepsis` disease + `dip_then_recovery` archetype**

```bash
grep -A 20 "^course_archetypes:" clinosim/modules/disease/reference_data/sepsis.yaml | grep -E "^  [a-z_]+:"
```

Expected includes `dip_then_recovery:`.

- [ ] **Step 3: Write the profile YAML**

Create `tests/fixtures/patient_profiles/jp_icu_sepsis_hai_clabsi.yaml`:

```yaml
profile_id: jp_icu_sepsis_hai_clabsi
disease_id: sepsis
country: JP
severity: severe
archetype: dip_then_recovery
count: 1
random_seed: 42
hospital_scale: large

patient_overrides:
  age: 74
  sex: M

force_hai_event:
  hai_type: clabsi
  onset_offset_days: 3
  organism_snomed: "3092008"  # S. aureus, CLABSI

description: |
  Severe JP ICU sepsis case with iatrogenic CLABSI onset day 3.
  Dip-then-recovery trajectory: initial deterioration → HAI complication
  → antibiotic de-escalation → recovery. Exercises the full HAI cascade
  narrative (culture reporting, empirical antibiotic switch, de-escalation).
  β-JP-1 target: JP ICU narrative + HAI event narrative.
clinical_notes: |
  Primary: sepsis (source: pneumonia)
  ICU admission day 0
  CVC placed for pressor support
  HAI CLABSI day 3 — S. aureus
  Empirical: vancomycin + piperacillin-tazobactam
  De-escalation on culture susceptibility
```

- [ ] **Step 4: Generate the golden**

```bash
clinosim regenerate-goldens --profile jp_icu_sepsis_hai_clabsi
```

- [ ] **Step 5: Sanity check — HAI narrative present**

```bash
python -c "
import json
g = json.load(open('tests/fixtures/patient_profiles/jp_icu_sepsis_hai_clabsi.golden.json'))
print('Documents:', len(g))
all_text = ' '.join(d.get('text', '') + ' '.join(d.get('sections', {}).values()) for d in g.values())
# Look for HAI-related narrative content (JP or EN)
for keyword in ('CLABSI', 'clabsi', 'カテーテル', 'catheter', 'S. aureus'):
    if keyword in all_text:
        print(f'HAI keyword found: {keyword}')
"
```

Expected: at least one HAI-related keyword present in the narrative.

- [ ] **Step 6: Determinism check**

```bash
clinosim regenerate-goldens --profile jp_icu_sepsis_hai_clabsi
git diff tests/fixtures/patient_profiles/jp_icu_sepsis_hai_clabsi.golden.json
```

Expected: no diff.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/patient_profiles/jp_icu_sepsis_hai_clabsi.yaml \
        tests/fixtures/patient_profiles/jp_icu_sepsis_hai_clabsi.golden.json
git commit -m "fixture(profiles): jp_icu_sepsis_hai_clabsi with HAI force (α-min-2c T7)

Profile #3: JP ICU severe sepsis + iatrogenic CLABSI day 3.
Elderly male (age 74) with dip-then-recovery trajectory. Forces HAI
CLABSI via force_hai_event={hai_type:clabsi, onset_offset_days:3,
organism_snomed:3092008 (S. aureus)}.

Exercises full HAI cascade narrative: culture + empirical antibiotic
+ de-escalation. Deterministic at seed 42.

β-JP-1 target: JP ICU narrative + HAI event narrative.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Profile #4 — `us_inpatient_diabetic_ketoacidosis`

**Files:**
- Create: `tests/fixtures/patient_profiles/us_inpatient_diabetic_ketoacidosis.yaml`
- Create: `tests/fixtures/patient_profiles/us_inpatient_diabetic_ketoacidosis.golden.json`

**Interfaces:** consumes T1-T3.

- [ ] **Step 1: Verify archetype**

```bash
grep -A 20 "^course_archetypes:" clinosim/modules/disease/reference_data/diabetic_ketoacidosis.yaml | grep -E "^  [a-z_]+:"
```

Expected includes `smooth_recovery:`.

- [ ] **Step 2: Write the profile YAML**

Create `tests/fixtures/patient_profiles/us_inpatient_diabetic_ketoacidosis.yaml`:

```yaml
profile_id: us_inpatient_diabetic_ketoacidosis
disease_id: diabetic_ketoacidosis
country: US
severity: severe
archetype: smooth_recovery
count: 1
random_seed: 42
hospital_scale: medium

patient_overrides:
  age: 34
  sex: F

description: |
  Severe US DKA case, smooth recovery trajectory. Young adult female
  with new-onset or exacerbated T1DM. Exercises glucose trajectory
  narrative, insulin drip management, and multi-day monitoring.
  β-JP-1 target: US inpatient endocrine narrative + drip protocol.
clinical_notes: |
  Presentation: nausea, vomiting, altered mental status
  Initial glucose > 400 mg/dL
  Ketones present, anion gap acidosis
  Insulin drip protocol
  Electrolyte replacement (K+, phos)
```

- [ ] **Step 3: Generate the golden**

```bash
clinosim regenerate-goldens --profile us_inpatient_diabetic_ketoacidosis
```

- [ ] **Step 4: Sanity check**

```bash
python -c "
import json
g = json.load(open('tests/fixtures/patient_profiles/us_inpatient_diabetic_ketoacidosis.golden.json'))
print('Documents:', len(g))
"
```

- [ ] **Step 5: Determinism check**

```bash
clinosim regenerate-goldens --profile us_inpatient_diabetic_ketoacidosis
git diff tests/fixtures/patient_profiles/us_inpatient_diabetic_ketoacidosis.golden.json
```

Expected: no diff.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/patient_profiles/us_inpatient_diabetic_ketoacidosis.yaml \
        tests/fixtures/patient_profiles/us_inpatient_diabetic_ketoacidosis.golden.json
git commit -m "fixture(profiles): us_inpatient_diabetic_ketoacidosis (α-min-2c T8)

Profile #4: US DKA severe smooth-recovery inpatient.
Young adult female (age 34) with DKA + insulin drip protocol.

Deterministic at seed 42. β-JP-1 target: US endocrine + drip narrative.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Profile #5 — `jp_inpatient_copd_exacerbation`

**Files:**
- Create: `tests/fixtures/patient_profiles/jp_inpatient_copd_exacerbation.yaml`
- Create: `tests/fixtures/patient_profiles/jp_inpatient_copd_exacerbation.golden.json`

**Interfaces:** consumes T1-T3.

- [ ] **Step 1: Verify archetype**

```bash
grep -A 20 "^course_archetypes:" clinosim/modules/disease/reference_data/copd_exacerbation.yaml | grep -E "^  [a-z_]+:"
```

Expected includes `dip_then_recovery:`.

- [ ] **Step 2: Write the profile YAML**

Create `tests/fixtures/patient_profiles/jp_inpatient_copd_exacerbation.yaml`:

```yaml
profile_id: jp_inpatient_copd_exacerbation
disease_id: copd_exacerbation
country: JP
severity: moderate
archetype: dip_then_recovery
count: 1
random_seed: 42
hospital_scale: medium

patient_overrides:
  age: 78
  sex: M

description: |
  JP elderly COPD exacerbation, dip-then-recovery trajectory.
  Chronic respiratory care scenario. Exercises O2 titration,
  nebulizer therapy, and steroid taper narratives.
  β-JP-1 target: JP chronic respiratory narrative.
clinical_notes: |
  History: 40 pack-year smoking, home O2 dependent
  Presentation: dyspnea, increased sputum
  Treatment: bronchodilators, systemic steroids, O2
  Recovery: gradual dyspnea improvement
```

- [ ] **Step 3: Generate the golden**

```bash
clinosim regenerate-goldens --profile jp_inpatient_copd_exacerbation
```

- [ ] **Step 4: Sanity check**

```bash
python -c "
import json
g = json.load(open('tests/fixtures/patient_profiles/jp_inpatient_copd_exacerbation.golden.json'))
print('Documents:', len(g))
"
```

- [ ] **Step 5: Determinism check**

```bash
clinosim regenerate-goldens --profile jp_inpatient_copd_exacerbation
git diff tests/fixtures/patient_profiles/jp_inpatient_copd_exacerbation.golden.json
```

Expected: no diff.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/patient_profiles/jp_inpatient_copd_exacerbation.yaml \
        tests/fixtures/patient_profiles/jp_inpatient_copd_exacerbation.golden.json
git commit -m "fixture(profiles): jp_inpatient_copd_exacerbation (α-min-2c T9)

Profile #5: JP COPD exacerbation moderate dip-then-recovery inpatient.
Elderly male (age 78) with chronic respiratory case + steroid taper.

Deterministic at seed 42. β-JP-1 target: JP chronic respiratory.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Profile #6 — `us_inpatient_hemorrhagic_stroke`

**Files:**
- Create: `tests/fixtures/patient_profiles/us_inpatient_hemorrhagic_stroke.yaml`
- Create: `tests/fixtures/patient_profiles/us_inpatient_hemorrhagic_stroke.golden.json`

**Interfaces:** consumes T1-T3.

- [ ] **Step 1: Verify archetype**

```bash
grep -A 20 "^course_archetypes:" clinosim/modules/disease/reference_data/hemorrhagic_stroke.yaml | grep -E "^  [a-z_]+:"
```

Expected includes `dip_then_recovery:`.

- [ ] **Step 2: Write the profile YAML**

Create `tests/fixtures/patient_profiles/us_inpatient_hemorrhagic_stroke.yaml`:

```yaml
profile_id: us_inpatient_hemorrhagic_stroke
disease_id: hemorrhagic_stroke
country: US
severity: severe
archetype: dip_then_recovery
count: 1
random_seed: 42
hospital_scale: large

patient_overrides:
  age: 71
  sex: F

description: |
  US neuro-critical hemorrhagic stroke, dip-then-recovery trajectory.
  Small hematoma, initial deterioration, then stabilization and
  gradual neuro recovery. Exercises GCS trajectory, neuro exam
  narrative, and rehab transfer planning.
  β-JP-1 target: US neuro-critical narrative + rehab handoff.
clinical_notes: |
  Presentation: sudden severe headache, left-sided weakness
  CT: right basal ganglia intracerebral hemorrhage
  ICU admission for neuro monitoring
  BP control, GCS q1h
  Recovery: stabilization by day 3, rehab consult
```

- [ ] **Step 3: Generate the golden**

```bash
clinosim regenerate-goldens --profile us_inpatient_hemorrhagic_stroke
```

- [ ] **Step 4: Sanity check**

```bash
python -c "
import json
g = json.load(open('tests/fixtures/patient_profiles/us_inpatient_hemorrhagic_stroke.golden.json'))
print('Documents:', len(g))
"
```

- [ ] **Step 5: Determinism check**

```bash
clinosim regenerate-goldens --profile us_inpatient_hemorrhagic_stroke
git diff tests/fixtures/patient_profiles/us_inpatient_hemorrhagic_stroke.golden.json
```

Expected: no diff.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/patient_profiles/us_inpatient_hemorrhagic_stroke.yaml \
        tests/fixtures/patient_profiles/us_inpatient_hemorrhagic_stroke.golden.json
git commit -m "fixture(profiles): us_inpatient_hemorrhagic_stroke (α-min-2c T10)

Profile #6: US hemorrhagic stroke severe dip-then-recovery inpatient.
Elderly female (age 71) with ICH, ICU stay, and rehab transfer.

Deterministic at seed 42. β-JP-1 target: US neuro-critical narrative.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: `tests/regression/` pytest suite

**Files:**
- Create: `tests/regression/__init__.py` (empty)
- Create: `tests/regression/conftest.py`
- Create: `tests/regression/test_narrative_profiles.py`
- Modify: `pyproject.toml` (register `regression` pytest marker)

**Interfaces:** consumes 6 profile YAMLs + 6 goldens from T5-T10; consumes `test-disease --patient-profile` from T2.

- [ ] **Step 1: Register the `regression` pytest marker**

Read `pyproject.toml` lines around 49 (`markers = [...]`). Add `regression` to the list:

```toml
markers = [
    "unit: unit tests",
    "integration: integration tests",
    "e2e: end-to-end tests",
    "regression: narrative regression suite (AD-66)",  # new
]
```

- [ ] **Step 2: Create `tests/regression/__init__.py`**

```bash
touch tests/regression/__init__.py
```

- [ ] **Step 3: Create `tests/regression/conftest.py`**

```python
"""AD-66 α-min-2c: narrative regression pytest suite configuration."""
from __future__ import annotations

from pathlib import Path


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "patient_profiles"


def profile_ids() -> list[str]:
    """Return sorted list of all profile ids (from *.yaml, excluding *.golden.json).

    Deterministic order (sorted) for parametrize stability.
    """
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.yaml"))
```

- [ ] **Step 4: Create `tests/regression/test_narrative_profiles.py`**

```python
"""AD-66 α-min-2c: byte-diff narrative regression suite.

For each canonical patient profile:
1. Subprocess-invoke `clinosim test-disease --patient-profile <id> --format cif -o <tmpdir>`
2. Walk cif/narratives/template/documents/**/*.json → build canonical dict
3. Load `<profile>.golden.json`
4. Assert dict equality; emit unified diff on mismatch

Marker `regression` = opt-in. Default `pytest` run does not execute this
suite (subprocess latency + β-JP-1 LLM cost budget considerations).
"""
from __future__ import annotations

import difflib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.regression.conftest import FIXTURE_DIR, profile_ids


@pytest.mark.regression
@pytest.mark.parametrize("profile_id", profile_ids())
def test_profile_narrative_byte_diff(profile_id: str, tmp_path: Path) -> None:
    """<profile>.yaml → generate → byte-diff vs <profile>.golden.json."""
    profile_path = FIXTURE_DIR / f"{profile_id}.yaml"
    assert profile_path.is_file(), f"missing profile YAML: {profile_path}"

    golden_path = FIXTURE_DIR / f"{profile_id}.golden.json"
    assert golden_path.is_file(), (
        f"missing golden JSON: {golden_path}. Run "
        f"`clinosim regenerate-goldens --profile {profile_id}` to bootstrap."
    )

    # 1. Subprocess-invoke test-disease pipeline
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "--patient-profile", str(profile_path),
         "--format", "cif", "-o", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, (
        f"test-disease failed for {profile_id}:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    # 2. Walk narrative output → canonical dict
    narr_dir = tmp_path / "cif" / "narratives" / "template" / "documents"
    if not narr_dir.is_dir():
        pytest.fail(f"no narratives written for {profile_id} (expected {narr_dir})")

    actual: dict[str, dict] = {}
    for enc_dir in sorted(narr_dir.iterdir()):
        if not enc_dir.is_dir():
            continue
        for doc_file in sorted(enc_dir.iterdir()):
            if doc_file.suffix != ".json":
                continue
            actual[doc_file.stem] = json.loads(doc_file.read_text())

    # 3. Load golden
    expected = json.loads(golden_path.read_text())

    # 4. Byte-diff
    if actual == expected:
        return

    # On mismatch, produce actionable unified diff
    actual_str = json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True)
    expected_str = json.dumps(expected, indent=2, ensure_ascii=False, sort_keys=True)
    diff = "\n".join(difflib.unified_diff(
        expected_str.splitlines(),
        actual_str.splitlines(),
        fromfile=f"{profile_id}.golden.json",
        tofile=f"{profile_id}.actual",
        lineterm="",
        n=3,
    ))
    pytest.fail(
        f"Narrative regression for {profile_id}:\n"
        f"If intentional, run `clinosim regenerate-goldens --profile "
        f"{profile_id}` + commit.\n\n{diff}"
    )
```

- [ ] **Step 5: Run the regression suite**

```bash
pytest -m regression -q
```

Expected: 6 tests PASS (one per profile).

If any fail, that means the profile YAML → golden JSON pipeline is not deterministic. Investigate by running `clinosim regenerate-goldens --profile <failing>` and re-checking `git diff` — if the diff is non-empty, the narrative pass has nondeterminism (should be reported as a separate bug, not fixed in this task).

- [ ] **Step 6: Verify default `pytest` does NOT run regression**

```bash
pytest tests/unit -x -q --collect-only | grep -c regression || echo "0 regression tests collected"
```

Expected: 0 regression tests in the unit collection (marker opt-in works).

- [ ] **Step 7: Commit**

```bash
git add tests/regression/ pyproject.toml
git commit -m "test(regression): AD-66 narrative profile byte-diff suite (α-min-2c T11)

New tests/regression/test_narrative_profiles.py parametrized over 6
canonical patient profiles. For each: subprocess-invoke test-disease
pipeline, walk cif/narratives/template/documents/*/*.json, byte-diff
against <profile>.golden.json. Unified-diff output on mismatch with
actionable regenerate-goldens command in failure message.

pytest marker 'regression' added to pyproject.toml (opt-in);
default pytest run does not execute this suite.

Companion CLI: clinosim regenerate-goldens (Task 3).
Companion docs: tests/fixtures/patient_profiles/README.md (Task 4).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: `docs/CONTRIBUTING-modules.md` addendum + `DESIGN.md` AD-66 ADR

**Files:**
- Modify: `docs/CONTRIBUTING-modules.md` (append section)
- Modify: `DESIGN.md` (append AD-66 ADR)

**Interfaces:** documentation only.

- [ ] **Step 1: Append CONTRIBUTING addendum**

Read `docs/CONTRIBUTING-modules.md`, then append at the end:

```markdown

## Adding a new patient profile fixture (AD-66)

See `tests/fixtures/patient_profiles/README.md` for the full workflow.
Quick summary:

1. Copy an existing profile YAML as a template
2. Edit `profile_id` (must match filename stem), `disease_id`, `country`, `severity`, `archetype`, `patient_overrides`
3. Run `clinosim regenerate-goldens --profile <new_profile_id>` to bootstrap the golden
4. Manually review `<new_profile_id>.golden.json`
5. Run `pytest -m regression -k <new_profile_id> -q` to verify
6. Commit YAML + golden together (AD-66 rule 1)

**AD-66 policy** (see `CLAUDE.md` for canonical wording):
- Profile YAML changes MUST regenerate golden + commit both together
- Unexpected `git diff` on goldens after intentional template changes = regression suspicion
```

- [ ] **Step 2: Append AD-66 ADR to `DESIGN.md`**

Read `DESIGN.md` to find the AD-65 ADR block (session 28 addition). Append AFTER AD-65:

```markdown

### AD-66 · Canonical patient profile fixture library for narrative regression

**Date:** 2026-07-03 (α-min-2c chain)

**Status:** Accepted

**Context:**
The AD-65 two-pass CIF architecture enables template narrative output to be
compared against a canonical baseline. β-JP-1 will introduce `LLMNarrativePass`
which produces non-deterministic LLM output. To detect narrative regression
(template drift, LLM drift, semantic changes), we need a canonical set of
deterministic patient profiles + expected narrative outputs to diff against.

**Decision:**
Ship 6 canonical patient profile YAML fixtures in `tests/fixtures/patient_profiles/`,
each accompanied by a `<profile>.golden.json` file containing the expected
template narrative output at seed 42. A `pytest -m regression` suite
subprocess-invokes `clinosim test-disease --patient-profile <id>` and byte-diffs
the generated narrative against the golden.

Introduce a new `PatientProfile` Pydantic type in `clinosim/types/config.py`
with `.to_forced_scenario()` transform, and a `clinosim regenerate-goldens`
CLI subcommand for bootstrap + re-generation.

Scope-in for α-min-2c: 6 disease-based inpatient/ICU profiles only.
Scope-out (deferred to β-JP-1 or later): ED/outpatient encounter profiles
(requires symmetric `test-encounter --patient-profile` extension), LLM
semantic diff mechanism, GitHub Actions CI integration, clinical review loop.

**Consequences:**

Positive:
- β-JP-1 unblocked — deterministic canonical patients for template vs LLM narrative regression
- Adding new profiles is a documented workflow (regenerate + review + commit)
- Bug A/B/C/D-style regressions detectable via narrative content diff
- Determinism enforced at seed 42 via existing AD-16 discipline

Negative:
- Additional maintenance burden when template narrative logic changes
  (all goldens need regeneration)
- Fixture library is separate from disease YAMLs (contributors need to
  understand both)

Neutral:
- 6 profiles × ~5-10 documents/profile × N sections = ~50-100 KB of golden
  JSON checked into git (acceptable)

**Alternatives considered:**

- **Input + narrative expectations in single YAML**: rejected — LLM output
  cannot be represented as expected substrings without semantic diff engine
  (deferred to β-JP-1 scope)
- **Input + reference golden narrative embedded (base64 in YAML)**: rejected
  — YAML would grow to 100-500 lines/profile, git diff becomes noisy, LLM
  parallel storage difficult
- **Integrated into existing AD-60 `audit run` framework**: rejected —
  fixture regression is per-profile deterministic byte-diff, not cohort
  statistics; overloading audit purpose

**Related:**
- AD-16 (determinism / seeded RNG discipline)
- AD-56 (CLI extensibility)
- AD-63 (document module)
- AD-65 (two-pass CIF)
- Spec: `docs/superpowers/specs/2026-07-03-tier1-3-alpha-min-2c-fixture-library-design.md`
- Plan: `docs/superpowers/plans/2026-07-03-tier1-3-alpha-min-2c-fixture-library-plan.md`
```

- [ ] **Step 3: Commit**

```bash
git add docs/CONTRIBUTING-modules.md DESIGN.md
git commit -m "docs: AD-66 ADR + CONTRIBUTING addendum (α-min-2c T12)

DESIGN.md AD-66: canonical patient profile fixture library ADR.
Context / Decision / Consequences / Alternatives / Related ADRs.

docs/CONTRIBUTING-modules.md: 'Adding a new patient profile fixture'
section with 6-step workflow, points to tests/fixtures/patient_profiles/
README.md for full detail.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 13: `CLAUDE.md` AD-66 rules + `TODO.md` fixture library entry COMPLETED

**Files:**
- Modify: `CLAUDE.md` (append AD-66 rules 1-2)
- Modify: `TODO.md` (mark `Post-AD-65 fixture library` COMPLETED; add deferred entries for ED/outpatient profiles + β-JP-1 semantic diff mechanism)

**Interfaces:** documentation only.

- [ ] **Step 1: Append AD-66 rules to CLAUDE.md**

Read `CLAUDE.md` to find the AD-65 section (session 28 addition). Append AFTER AD-65 rules:

```markdown

### AD-66 · Canonical patient profile fixture library (α-min-2c)

**Rule 1**: Profile YAML changes MUST regenerate golden + commit both together.
Modifying `tests/fixtures/patient_profiles/<name>.yaml` without a
corresponding `<name>.golden.json` update = the regression suite will fail
at the next `pytest -m regression` run. Regenerate via `clinosim
regenerate-goldens --profile <name>`.

**Rule 2**: Unexpected `git diff` on goldens after intentional template
changes = regression suspicion. When narrative template logic is
intentionally modified (e.g., adding a new section, changing wording),
`clinosim regenerate-goldens --all` will produce a diff — inspect the diff
carefully. If the diff includes changes to profiles you did NOT
intentionally affect (e.g., you only touched the `admission_hp` template
but goldens for `us_inpatient_hemorrhagic_stroke` progress notes also
changed), that indicates a regression in the narrative pass. Investigate
BEFORE committing the golden diff.
```

- [ ] **Step 2: Mark TODO.md fixture library entry COMPLETED + add deferred entries**

Read `TODO.md` around line 1439-1452 (fixture library entry). Modify:

Replace:
```markdown
### Post-AD-65 fixture library (α-min-2c or β-2 chain)

- `clinosim/tests/fixtures/patient_profiles/` canonical fixture YAML gallery (10-15 exemplar profiles)
- Clinical archetypes:
  - Healthy outpatient (no chronic conditions, preventive care only)
  - Simple chronic (1 stable disease, routine medication, no complications)
  - Complex polypharmacy (3+ conditions, drug interactions, high-acuity potential)
  - Acute-on-chronic (exacerbation of known disease + unrelated ED visit)
  - HAI cohort (ICU-to-discharge with CLABSI/CAUTI/VAP lifecycle)
  - Multilinguality testing (JP locale + JP-language narrative validation)
- `clinosim test-disease --patient-profile <yaml>` CLI 対応 — fixture profile を入力に selected-disease simulation 実行
- Fixture profile schema: patient_id / demographics / chronic_medications / initial_labs / encounter_sequence / narrative_expectations
- Fixture 選定は臨床医 review loop 必須(小児科医 + 内科医 +看護師 validation per archetype)
- CI regression suite として integrate — narrative generation + FHIR export の determinism + bug tail tracking
```

With:
```markdown
### Post-AD-65 fixture library (α-min-2c) — ✅ COMPLETED

Shipped in PR #NNN (α-min-2c chain, session 30, AD-66).
Delivered:
- `tests/fixtures/patient_profiles/` with 6 canonical profiles
- `PatientProfile` Pydantic type in `clinosim/types/config.py`
- `test-disease --patient-profile` CLI + `regenerate-goldens` CLI
- `pytest -m regression` suite

### Post-α-min-2c fixture library extensions (β-JP-1 or later)

- Encounter-based profiles (ED / outpatient) — requires symmetric
  `test-encounter --patient-profile` extension + `PatientProfile.condition_id`
  field, or unified `test-profile` verb
- Additional disease-based profiles beyond α-min-2c 6 (as β-JP-1 LLM
  regression scope grows)
- LLM semantic diff mechanism — byte-diff insufficient for LLM output
  (fuzzy match, tolerance thresholds, expected phrase substrings)
- Clinical review loop — per-profile physician + nurse validation
- CI GitHub Actions workflow for automated regression at PR time
- LLM parallel goldens (`<profile>.llm-<model>.golden.json`) alongside
  `<profile>.golden.json`
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md TODO.md
git commit -m "docs(claude-todo): AD-66 rules 1-2 + TODO fixture library COMPLETED (α-min-2c T13)

CLAUDE.md AD-66 rules:
- Rule 1: Profile YAML changes MUST regenerate golden + commit together
- Rule 2: Unexpected golden diff on unrelated profiles = regression
  suspicion — investigate BEFORE committing

TODO.md:
- Post-AD-65 fixture library entry → COMPLETED (PR #NNN)
- New 'Post-α-min-2c fixture library extensions' section with 6
  deferred items (ED/outpatient profiles, LLM semantic diff, clinical
  review loop, CI workflow, LLM parallel goldens)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Final verification (post-T13)

- [ ] **Verify no unit regressions**

```bash
pytest tests/unit -x -q
```

Expected: all previously-passing unit tests still PASS + new T1/T2/T3 tests PASS.

- [ ] **Verify regression suite passes**

```bash
pytest -m regression -q
```

Expected: 6 profile regression tests PASS.

- [ ] **Verify integration tests still pass**

```bash
pytest tests/integration -x -q -m integration
```

Expected: 0 failures.

- [ ] **Ruff clean on all touched files**

```bash
ruff check clinosim/types/config.py clinosim/simulator/cli.py \
    tests/unit/test_patient_profile.py \
    tests/unit/test_cli_patient_profile.py \
    tests/unit/test_cli_regenerate_goldens.py \
    tests/regression/
```

Expected: 0 errors (pre-existing violations elsewhere are out of scope).

- [ ] **Mypy strict on touched product code**

```bash
mypy --strict clinosim/types/config.py clinosim/simulator/cli.py
```

Expected: 0 new errors (repo-wide baseline unchanged).

- [ ] **Final commit review**

```bash
git log --oneline --graph -20
```

Expected: 13 clean per-task commits (or aggregated as reviewer prefers).

---

## Chain execution (post-plan)

After all 13 tasks land + verification passes, the chain proceeds through:

**Stage 2** — Final whole-branch opus review (catches stale-test / API drift; e.g., session 28's 62-test migration surprise)

**Stage 3** — Adv-1 5-lens fan-out:
- Lens 1: silent no-op (`PatientProfile` extra=forbid actually rejects; `regenerate-goldens` sort_keys deterministic; golden regeneration idempotent)
- Lens 2: data unification (`FIXTURE_DIR` single source in conftest.py; no dup literals)
- Lens 3: FHIR compliance (n/a — no new FHIR emission)
- Lens 4: determinism + scale (seed 42 respected; sorted dir iteration; no `datetime.now`/`uuid.uuid4` in narrative pass)
- Lens 5: spec + memory + CLAUDE.md (all 15 sections implemented; AD-66 rules 1-2 enforced; TODO entries updated correctly)

**Stage 4** — Adv-2 self-regression on adv-1 fix commits

**Merge** → 12 例目 4-stage adversarial chain converged.
