# Tier 1 #3 α-min-2c — Canonical Patient Profile Fixture Library for Narrative Regression

**Date**: 2026-07-03
**Chain**: Tier 1 #3 α-min-2c (session 30)
**Follows**: PR #131 (α-min-2b AD-65 Two-pass CIF Restoration + adv-1 + adv-2)
**Blocks**: β-JP-1 LLMNarrativePass (regression testing infrastructure prerequisite)
**Related ADRs**: AD-16 (determinism), AD-30 (CIF language-neutral), AD-55 (Base vs Module), AD-56 (extensibility), AD-60 (audit framework), AD-63 (document module), AD-65 (two-pass CIF)

## 0. Overview

α-min-2c fixture library establishes a **canonical set of 6 deterministic patient profile YAMLs + accompanying golden narrative JSONs** in `tests/fixtures/patient_profiles/`, plus a `pytest -m regression` suite that byte-diffs generated narrative output vs golden. The library is the foundation on which β-JP-1's `LLMNarrativePass` will be regression-tested — template narrative goldens land in α-min-2c, LLM narrative goldens land in β-JP-1 as `<profile>.llm-<model>.golden.json` alongside.

Non-goals (deferred to β-JP-1 or later):
- LLM narrative semantic diff mechanism
- `.github/workflows/` GitHub Actions integration (manual `pytest -m regression` sufficient)
- Clinical review loop (per-profile 臨床医 review)
- FHIR output regression (existing e2e goldens already cover)
- LLM model comparison suite

## 1. Design decisions (brainstorming outcomes)

| # | Axis | Decision | Rationale |
|---|---|---|---|
| 1 | Primary goal | β-JP-1 preparation | Bug A/B/C/D already covered by existing integration tests + audit gates; fixture library's unique value is deterministic canonical profiles for narrative regression |
| 2 | Profile shape | Input-only YAML + separate golden JSON | Separation of concerns; golden = byte-diff-able; β-JP-1 slots in via parallel `<profile>.llm-<model>.golden.json` |
| 3 | Profile count | 6 minimal profiles | LLM regression cost minimization; each archetype × locale representative |
| 4 | Regression mechanism | Exact byte-diff pytest suite | Simplest, catches 1-byte drift; existing pytest infra; β-JP-1 extends with semantic diff |
| 5 | Type integration | New `PatientProfile` Pydantic + `.to_forced_scenario()` | Type safety; validated schema; β-JP-1 LLM-specific field slots reserved (llm_seed, expected_section_lengths) |

## 2. Directory layout

```
tests/
  fixtures/
    patient_profiles/
      README.md                              # Profile 追加 workflow + schema doc
      jp_inpatient_bacterial_pneumonia.yaml
      jp_inpatient_bacterial_pneumonia.golden.json
      us_inpatient_mi.yaml
      us_inpatient_mi.golden.json
      jp_icu_sepsis_hai_clabsi.yaml
      jp_icu_sepsis_hai_clabsi.golden.json
      us_ed_chest_pain_noncardiac.yaml
      us_ed_chest_pain_noncardiac.golden.json
      jp_outpatient_dm_type2.yaml
      jp_outpatient_dm_type2.golden.json
      us_inpatient_dka.yaml
      us_inpatient_dka.golden.json
  regression/
    __init__.py
    conftest.py                              # pytest marker registration + fixture loader
    test_narrative_profiles.py               # parametrized byte-diff suite
```

**Naming convention**: `<country>_<encounter_type>_<condition_slug>.yaml`
- `country`: `us` / `jp`
- `encounter_type`: `inpatient` / `icu` / `ed` / `outpatient` / `rehab`
- `condition_slug`: disease_id or condition_id verbatim (underscore-separated)

**Layout rationale**:
- `tests/fixtures/` = pytest convention for fixture data; integrates naturally with existing `tests/unit/` `tests/integration/` `tests/e2e/`
- `<profile>.yaml` + `<profile>.golden.json` sibling placement = grep + navigation ease (Session 24 pattern: sibling colocation)
- `tests/regression/` parallel to existing test dirs; pytest marker `regression` for opt-in run

## 3. `PatientProfile` type

**Location**: `clinosim/types/config.py` (adjacent to existing `ForcedScenario` — semantic domain match)

**Definition**:
```python
class PatientProfile(BaseModel):
    """Canonical patient scenario fixture for narrative regression testing (α-min-2c).

    Loaded from tests/fixtures/patient_profiles/<name>.yaml.
    Transformed to ForcedScenario at CLI dispatch time via .to_forced_scenario().
    β-JP-1 will extend with LLM-specific fields (llm_seed, expected_sections, ...).
    """

    # --- Identity ---
    profile_id: str  # matches YAML filename stem, e.g. "jp_inpatient_bacterial_pneumonia"

    # --- Simulation inputs (fed to ForcedScenario) ---
    disease_id: str
    country: str = "US"  # "US" | "JP"
    severity: str | None = None  # "mild" | "moderate" | "severe" — None = disease default
    archetype: str | None = None
    count: int = 1  # regression suite always uses count=1 (deterministic)
    random_seed: int = 42  # SimulatorConfig-level seed
    hospital_scale: str = "medium"  # "small" | "medium" | "large"

    # --- Optional overrides ---
    patient_overrides: dict = {}  # age / sex / etc, passed to ForcedScenario
    force_hai_event: dict | None = None  # PR3b-1 shape, passed through
    chronic_medications: list[str] = []  # RxNorm keys; empty = no chronic meds forced
    time_range: tuple[str, str] = ("2024-04-01", "2025-03-31")

    # --- Documentation ---
    description: str = ""  # human-readable "why this profile exists"
    clinical_notes: str = ""  # multi-line clinical rationale (optional)

    # --- β-JP-1 reserved slots (unused in α-min-2c, present for forward-compat) ---
    # llm_seed: int | None = None
    # expected_section_lengths: dict[str, tuple[int, int]] | None = None

    def to_forced_scenario(self) -> ForcedScenario:
        return ForcedScenario(
            disease_id=self.disease_id,
            count=self.count,
            severity=self.severity,
            archetype=self.archetype,
            patient_overrides=self.patient_overrides,
            force_hai_event=self.force_hai_event,
        )
```

**Loader**:
```python
def load_patient_profile(name_or_path: str) -> PatientProfile:
    """Resolve profile by name (lookup in tests/fixtures/patient_profiles/) or absolute path.

    Raises FileNotFoundError with actionable message when unresolvable.
    Raises ValidationError on schema mismatch (Pydantic strict mode).
    Raises ValueError when profile_id mismatches filename stem (invariant).
    """
```

**Invariants** (all fail-loud, PR-90 lesson):
1. `profile_id` MUST match filename stem — raise on mismatch
2. Unknown YAML keys MUST reject — Pydantic `model_config = {"extra": "forbid"}`
3. `chronic_medications` entries MUST pass `code_lookup("rxnorm", code)` = existing canonical constant
4. `country` MUST be `"US"` or `"JP"` — enum check
5. `severity` MUST be `None` or in `{"mild", "moderate", "severe"}` when non-None
6. `disease_id` MUST exist in disease_protocol OR encounter_condition registry — verified at load time

## 4. CLI integration

**Extended command**: `clinosim test-disease [--patient-profile <name-or-path>] [disease_id] [OPTS]`

**Argument semantics**:
- `--patient-profile <arg>`: new optional flag
- `disease_id` positional: now `nargs='?'` (optional when `--patient-profile` given)
- `--severity` / `--archetype` / `--seed` / `--country`: CLI values override profile values (dev iteration flexibility) — stderr warn on divergence (Bug D lesson)
- `-o` / `--format`: unchanged (existing AD-65 Phase 4 semantics)

**Dispatch flow** (in `_run_test_disease_generate`):
```python
if args.patient_profile:
    profile = load_patient_profile(args.patient_profile)
    # CLI overrides
    if args.disease_id and args.disease_id != profile.disease_id:
        print(f"WARN: --patient-profile disease_id={profile.disease_id} differs from positional {args.disease_id}; using CLI arg", file=sys.stderr)
        profile = profile.model_copy(update={"disease_id": args.disease_id})
    if args.severity is not None:
        profile = profile.model_copy(update={"severity": args.severity})
    if args.archetype is not None:
        profile = profile.model_copy(update={"archetype": args.archetype})
    if args.seed is not None:
        profile = profile.model_copy(update={"random_seed": args.seed})
    if args.country is not None:
        profile = profile.model_copy(update={"country": args.country})
    scenario = profile.to_forced_scenario()
    config = SimulatorConfig(random_seed=profile.random_seed, country=profile.country, hospital_scale=profile.hospital_scale)
else:
    # legacy path unchanged
    scenario = ForcedScenario(disease_id=args.disease_id, ...)
    config = SimulatorConfig(...)
```

**Override policy** (Bug D lesson — explicit user-typed CLI arg is more visible than implicit YAML config, so explicit wins with a stderr warn):
- Positional `disease_id` differs from profile → warn + **positional wins**
- Explicit `--severity` / `--archetype` / `--seed` / `--country` differs from profile → warn + **CLI arg wins**
- Nothing implicitly overrides — the warn is always emitted so silent divergence is impossible

**Error paths** (all fail-loud):
- Profile not found → `sys.exit(2)` with actionable message + list of known profile ids
- Profile invalid schema → `sys.exit(2)` with Pydantic error message
- Profile `disease_id` unknown to disease_protocol / encounter_condition registries → `sys.exit(2)` with error message

**Non-Q4 subcommand**: `test-encounter` NOT extended in α-min-2c. Profile #4 (`us_ed_chest_pain_noncardiac`) uses `test-disease --patient-profile` where `chest_pain_noncardiac` is dispatched to encounter-simulation path. If not currently supported, add a scope-in fix (verify at Task 8 time).

## 5. Regression pytest suite

**Files**: `tests/regression/conftest.py` + `tests/regression/test_narrative_profiles.py`

**conftest.py**:
```python
import pytest
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "patient_profiles"

def profile_ids() -> list[str]:
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.yaml"))

def pytest_configure(config):
    config.addinivalue_line("markers", "regression: profile narrative regression suite")
```

**test_narrative_profiles.py**:
```python
import json
import subprocess
import sys
import difflib
import pytest
from pathlib import Path
from tests.regression.conftest import FIXTURE_DIR, profile_ids

@pytest.mark.regression
@pytest.mark.parametrize("profile_id", profile_ids())
def test_profile_narrative_byte_diff(profile_id: str, tmp_path: Path) -> None:
    """AD-66 α-min-2c: <profile>.yaml → generate → byte-diff vs <profile>.golden.json."""
    subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "--patient-profile", profile_id,
         "--format", "cif", "-o", str(tmp_path)],
        check=True, capture_output=True, text=True,
    )
    # Walk narrative output → build canonical dict
    narr_dir = tmp_path / "cif" / "narratives" / "template" / "documents"
    actual = {}
    for enc_dir in sorted(narr_dir.iterdir()):
        for doc_file in sorted(enc_dir.iterdir()):
            actual[doc_file.stem] = json.loads(doc_file.read_text())
    golden_path = FIXTURE_DIR / f"{profile_id}.golden.json"
    expected = json.loads(golden_path.read_text())
    if actual != expected:
        diff = "\n".join(difflib.unified_diff(
            json.dumps(expected, indent=2, ensure_ascii=False).splitlines(),
            json.dumps(actual, indent=2, ensure_ascii=False).splitlines(),
            fromfile=f"{profile_id}.golden.json",
            tofile=f"{profile_id}.actual",
            lineterm="",
        ))
        pytest.fail(f"Narrative regression for {profile_id}:\n{diff}")
```

**Rationale**:
- **subprocess**, not in-process: `test-disease` = full pipeline (structural CIF + narrative pass + FHIR export); production path exercised. In-process risks fixture cache / global state leak → flaky.
- **sorted dir iteration**: deterministic walk order regardless of filesystem ordering (AD-16 discipline).
- **difflib unified diff**: actionable failure output (readable by human, git-diff-style).
- **`ensure_ascii=False`**: preserve JP characters in diff output for JP profiles.

**Golden bootstrap workflow** (dev CLI):
`clinosim regenerate-goldens [--profile <name>|--all]`
1. `--all` → iterate 6 profiles; `--profile X` → single profile
2. Per profile: run `test-disease` pipeline
3. Walk narrative output (same as regression suite)
4. Write to `tests/fixtures/patient_profiles/<profile>.golden.json` (overwrite existing)
5. stderr: `"Regenerated N goldens. Review + git diff + commit if intentional."`

**Golden update workflow** (documented in `README.md`):
1. Intentionally change template (e.g., add new section)
2. Run `clinosim regenerate-goldens --all`
3. `git diff tests/fixtures/patient_profiles/*.golden.json` — visual review
4. Unexpected diff → regression suspicion → revert or fix implementation
5. Expected diff → commit both YAML (if changed) and golden

**Pytest invocation**:
- Default `pytest` run: regression SKIPPED (marker opt-in)
- Explicit: `pytest -m regression -q` or `pytest tests/regression/ -q`
- Future CI: `pytest -m regression --strict-markers`

## 6. Initial 6 profiles (clinical content)

| # | profile_id | disease_id | severity | archetype | country | Verification focus |
|---|---|---|---|---|---|---|
| 1 | `jp_inpatient_bacterial_pneumonia` | `bacterial_pneumonia` | moderate | `uncomplicated_improvement` | JP | Multi-day progress note (3-5 days LOS), JP linguistic expression |
| 2 | `us_inpatient_mi` | `acute_myocardial_infarction` | severe | `pci_complicated` | US | Troponin trajectory + PCI narrative, US H&P + Discharge summary |
| 3 | `jp_icu_sepsis_hai_clabsi` | `sepsis` | severe | `icu_prolonged` | JP | `force_hai_event={"hai_type":"clabsi","onset_offset_days":3,"organism_snomed":"3092008"}` = HAI + antibiotic de-escalation |
| 4 | `us_ed_chest_pain_noncardiac` | `chest_pain_noncardiac` | moderate | — | US | ED triage narrative (ESI) + ED note, single-encounter |
| 5 | `jp_outpatient_dm_type2` | `diabetes_type2` | mild | — | JP | Outpatient SOAP + JP chronic med list |
| 6 | `us_inpatient_dka` | `dka` | severe | `insulin_drip_recovery` | US | Glucose trajectory + insulin drip, H&P + progress + discharge |

**Encounter path verification** (Task 8): Profile 4's `disease_id=chest_pain_noncardiac` is a `condition_id` (encounter registry), not `disease_id` (disease registry). `test-disease` currently dispatches by disease_protocol lookup — if `chest_pain_noncardiac` is NOT in that registry, Task 8 MUST decide: (a) extend `test-disease` dispatch to fall back to encounter_condition registry, OR (b) rename profile to `us_ed_encounter_chest_pain_noncardiac` + use `test-encounter --patient-profile`. Preferred = (a), single CLI verb.

**Archetype validity** (Tasks 5-10): Each `archetype` MUST exist in the target disease YAML's `course_archetypes`. Task 4 must verify before authoring profile YAMLs — grep disease YAML, use exact archetype name.

**Determinism** (Tasks 5-10): Every profile MUST include `random_seed: 42` (or a documented alternative). Golden bootstrap runs with this seed; test suite runs with this seed; determinism verified via `test-disease` byte-diff invariant.

## 7. Documentation deliverables

1. **`tests/fixtures/patient_profiles/README.md`**:
   - Purpose (β-JP-1 blocker)
   - Profile creation workflow (clone existing → edit → regenerate → commit)
   - Schema doc (PatientProfile YAML fields with 1-line description each + example)
   - Naming convention + directory layout
   - Regression suite integration (pytest -m regression)
2. **`docs/CONTRIBUTING-modules.md` addendum**:
   - "Adding a new patient profile fixture" section (README.md 参照 + `regenerate-goldens` example)
3. **`DESIGN.md` AD-66 ADR**:
   - "Canonical patient profile fixture library for narrative regression"
   - Context / Decision / Consequences / Alternatives (input+golden vs single YAML vs inline embedded) / Related ADRs (AD-16, AD-63, AD-65)
4. **`CLAUDE.md`**:
   - AD-66 rule 1: "Profile YAML changes MUST regenerate golden + commit both together"
   - AD-66 rule 2: "Golden 差分は intentional narrative change を意味する — 予期しない diff = regression suspicion"
5. **`MODULES.md`**: No module addition (`tests/fixtures/` is not a module) — "22 modules" claim unchanged
6. **`TODO.md`**:
   - `Post-AD-65 fixture library` entry → mark COMPLETED with PR #NNN link
   - Add explicit `β-JP-1 semantic diff mechanism` new entry (α-min-2c defers this)

## 8. SDD task breakdown (~15 tasks)

| Task | Content | Est. diff |
|---|---|---|
| T1 | `PatientProfile` Pydantic type + `load_patient_profile()` + unit tests | ~150 lines |
| T2 | `test-disease --patient-profile` CLI wiring + error paths + unit tests | ~200 lines |
| T3 | `regenerate-goldens` CLI subcommand + unit tests | ~150 lines |
| T4 | `tests/fixtures/patient_profiles/README.md` + directory bootstrap | ~100 lines docs |
| T5 | Profile #1 JP inpatient bacterial pneumonia + golden bootstrap | ~30 YAML + N JSON |
| T6 | Profile #2 US inpatient MI + golden bootstrap | 同 |
| T7 | Profile #3 JP ICU sepsis HAI CLABSI + golden bootstrap | 同 |
| T8 | Profile #4 US ED chest_pain (encounter path verify or scope-in fix) + golden bootstrap | 同 + dispatch verify |
| T9 | Profile #5 JP outpatient DM_type2 + golden bootstrap | 同 |
| T10 | Profile #6 US inpatient DKA + golden bootstrap | 同 |
| T11 | `tests/regression/conftest.py` + `test_narrative_profiles.py` pytest suite | ~150 lines |
| T12 | `docs/CONTRIBUTING-modules.md` addendum + DESIGN.md AD-66 ADR | ~200 lines docs |
| T13 | CLAUDE.md AD-66 rules (1-2) + TODO.md fixture library entry COMPLETED update | ~30 lines |
| T14 | Final whole-branch review + adv-1 5-lens fan-out prep | (subagent, no diff) |
| T15 | Session memory update + PR body | ~100 lines |

**Total**: 15 tasks, ~1 session (session 26/27/28/29 pattern).

## 9. Chain execution pattern

- **Stage 1**: 15 SDD tasks via subagent-driven-development (fresh implementer + task reviewer per task, ledger tracking)
- **Stage 2**: Final opus whole-branch review (catches API-drift stale tests, like session 28's 62-test migration)
- **Stage 3**: adv-1 5-lens fan-out (silent-no-op / data-unification / FHIR-JP-Core / determinism-scale / spec-memory-CLAUDE.md)
- **Stage 4**: adv-2 self-regression (fix commits verified against session 22 stage-3 regression pattern)
- Merge → **12 例目 4-stage adversarial chain converged**

## 10. Global constraints (applies to all tasks)

- **CLAUDE.md AD-65 rules 1-5**: preserved (narrative wrapper access, structural stubs, POST_SIMULATION pass, walk order, FHIR builder wrapper access)
- **CIF→FHIR no-drop invariant** (feedback_cif_to_fhir_no_drop): applies — but α-min-2c does NOT emit new FHIR resources, so no matrix additions
- **AD-16 determinism**: profile fixtures use fixed seeds (default 42); golden regeneration must be byte-diff-stable at seed 42
- **Scope discipline** (feedback_scope_discipline): 6 profiles only; no CI workflow; no clinical review loop; no semantic diff — all deferred to TODO.md at spec-write time (already done in §0 Non-goals + §7 doc 6)
- **Canonical single source** (feedback_unify_data_logic): fixture dir path constants (`FIXTURE_DIR`) defined ONCE in `conftest.py`, imported everywhere
- **PR-90 silent no-op defense**: PatientProfile validates schema strictly (extra=forbid), profile_id filename match, disease_id registry lookup, RxNorm code lookup — all fail-loud at load time

## 11. Success criteria

- [ ] All 15 SDD tasks land with passing unit tests
- [ ] 6 profile YAMLs + 6 golden JSONs committed and readable
- [ ] `pytest -m regression` passes on all 6 profiles at seed 42
- [ ] `clinosim regenerate-goldens --all` idempotent (running twice = zero diff)
- [ ] `clinosim test-disease --patient-profile jp_inpatient_bacterial_pneumonia -o /tmp/x` produces cif/narratives/template/documents/
- [ ] Adv-1 5-lens verdict: ≤ 3 Critical + Important fixed in fix commits
- [ ] Adv-2 verdict: Ship-ready or ≤ 2 cosmetic fixups
- [ ] Full `pytest tests/unit -x -q` remains green (no unit regressions)
- [ ] Full `pytest tests/integration -x -q -m "integration"` remains green
- [ ] Merged to master

## 12. Risks + mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Profile 4 (`chest_pain_noncardiac`) is encounter_id not disease_id → `test-disease` dispatch fails | High (Task 8 blocker) | Scope-in verify at T8; extend dispatch OR rename profile |
| Golden JSON is nondeterministic across runs (RNG drift) | Critical (regression flaky) | Fixed seed 42; investigate any nondeterminism via `test_narrative_pass_determinism.py`-style test |
| Multi-day progress notes produce different filenames on re-run | Medium (session 28 special note #1 lesson) | Filename derived from document_id; `_find_matching_stubs` returns list; verified at T5 |
| PatientProfile schema drift from ForcedScenario | Low | Unit test at T1: `PatientProfile.to_forced_scenario()` round-trip = identity |
| `regenerate-goldens` overwrites without confirmation → user loses uncommitted goldens | Low | Documented workflow; git diff visual review is the safeguard |
| β-JP-1 discovers PatientProfile lacks LLM-required fields | Medium (future refactor) | Reserved slots (`llm_seed` commented) documented in type; β-JP-1 extends non-breakingly |

## 13. β-JP-1 forward-compatibility contract

α-min-2c is explicitly a **β-JP-1 blocker**. The type and layout choices lock in:
1. **Golden filename convention**: `<profile>.golden.json` = template Stage 2 output; β-JP-1 adds `<profile>.llm-<model>.golden.json` alongside — no rename needed
2. **Regression parametrize**: `profile_ids()` walks `*.yaml`, β-JP-1 adds `--narrative-version llm-<model>` axis to the parametrize matrix
3. **PatientProfile reserved slots**: `llm_seed`, `expected_section_lengths` fields commented in type; β-JP-1 uncomments + populates
4. **CLI**: `test-disease --patient-profile X --narrative-version llm-<model>` already possible (AD-65 F-1 CIFReader raises on unknown version — fail-loud when β-JP-1 not yet run)

**β-JP-1's expected additions on top of α-min-2c** (documented for context, NOT scope):
- Semantic diff engine for LLM output (fuzzy match, tolerance thresholds)
- `<profile>.llm-<model>.golden.json` bootstrap flow
- LLM regression cost budget (bedrock cache + retries)
- `narrate --patient-filter` for iterative LLM tuning

## 14. Change log

| Date | Author | Summary |
|---|---|---|
| 2026-07-03 | Session 30 controller | Initial design based on 5 brainstorming decisions |
