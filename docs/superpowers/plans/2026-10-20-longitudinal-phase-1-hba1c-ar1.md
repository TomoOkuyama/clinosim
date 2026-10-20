# Longitudinal state evolution — Phase 1 (framework + HbA1c AR(1)) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the longitudinal-state-evolution framework and migrate HbA1c to be a year-indexed AR(1) latent on `PersonRecord.state_history`, retiring the `glycemic_control` proxy as the authoritative source.

**Architecture:** New `clinosim.modules.longitudinal` package (engine + patterns/ar1 + loader + YearSnapshot). The aging driver calls `engine.advance_one_year(person, year, year_rng)` annually; per-encounter emit calls `engine.state_at(person, when).continuous["hba1c"]` instead of `hba1c_from_glycemic_control(gc)`. The existing `_advance_glycemic_trajectory` aging pass is retired; `PersonRecord.glycemic_trajectory` is replaced by `PersonRecord.state_history: list[YearSnapshot]`.

**Tech Stack:** Python 3.12, numpy Generator for RNG, pydantic for yaml schema validation, dataclasses for YearSnapshot. yaml loader via `functools.cache`. pytest + pytest-xdist for test shards.

**Spec:** [docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md](../specs/2026-10-20-longitudinal-state-evolution-design.md)

## Global Constraints

- **Determinism (reproduce.sh gate):** same (seed, code version, config, country, start, end, population) → byte-identical output. Draw from the passed Generator exactly once per attribute per (person, year), in topologically-sorted attribute order. No wall-clock seeding, no internal sub-seed namespace in Phase 1.
- **Byte-identity across the migration is non-goal (per spec §2.3).** Every patient's byte stream shifts; adult-only cohorts without any E11/E10 patient still shift via the driver's cursor.
- **Phase 1 attribute scope:** HbA1c only. The AR(1) pattern yaml declares `clinical_scope.requires_chronic_codes: ["E11", "E10"]` and `requires_age_band: [18, 120]`, so children and non-DM persons do not get a HbA1c latent entry (their `YearSnapshot.continuous` has no `"hba1c"` key).
- **AR(1) parameters are literature-calibrated.** Pin exact values from the Phase 1 pre-work artefact ([scratchpad/s104_cohort/hba1c_ar1_calibration.md](/private/tmp/claude-818441110/-Users-tokuyama-workspace-clinosim/7d402617-622a-4566-b0dd-6c4896ada4a3/scratchpad/s104_cohort/hba1c_ar1_calibration.md)):
  - `mu_init = 1.95`, `sigma_init = 0.17` (lognormal log-scale, clamp [4.5, 14.0])
  - `phi = 0.75`, `sigma_innovation = 0.40`, `mean_reversion_target = 7.3`
  - `sigma_measurement = 0.20`, latent clamp `[4.0, 15.0]`
- **No new RNG namespace prefix.** The aging driver's existing per-person per-year generator passed through to `advance_one_year` is the only stream in Phase 1.
- **Protocol override backstop:** `clinosim/simulator/inpatient.py:627-628` sets `state.glycemic_control = protocol.chronic_glycemic_control` for disease-sim protocols that force a specific metabolic context. The HbA1c emit path (`clinosim/modules/physiology/engine.py:918-946`) MUST still honour `state.glycemic_control` when set, falling through to `state_at(person, when).continuous["hba1c"]` only when `state.glycemic_control is None`. The `hba1c_from_glycemic_control(gc)` helper function stays — it is the protocol-override translation; what is retired is `PersonRecord.glycemic_trajectory` and `PatientProfile.glycemic_control` as per-patient state.
- **Idempotency contract:** `advance_one_year(person, year)` raises `ValueError` if `person.state_history[-1].year == year`. The aging driver guarantees single-call per (person, year).

## Review Focus

Classes of input / failure the spec implies but no step's assertions cover directly. Each gets a test added below in its owning task.

1. **A DM patient admitted mid-year has `state_at(encounter)` return the sim-year snapshot, not the admission-month one.** The spec's year-granularity means intra-year encounters resolve to the same `YearSnapshot`. The failure mode is wrong year arithmetic across a December-31 vs January-1 boundary — pinned by `test_state_at_lookup.py::test_year_boundary_encounters_resolve_to_correct_snapshot`.
2. **A non-DM patient's `YearSnapshot.continuous` has no `"hba1c"` key.** The spec's `clinical_scope.requires_chronic_codes` gate must drop the attribute entirely for non-E11/E10 persons. The failure mode is HbA1c being written for non-DM patients because the gate was ignored — pinned by `test_hba1c_physiological_bounds.py::test_non_dm_patient_has_no_hba1c_in_state_history`.
3. **A patient aged into E11 mid-sim (new chronic onset at year y3 of a 5y sim) has `state_history[0..y2]` without `hba1c` and `state_history[y3..]` with `hba1c`.** Phase 1 does not wire new-onset DM but the engine's behaviour under in-sim scope change must be defined — pinned by `test_longitudinal_engine_integration.py::test_mid_sim_scope_entry_starts_hba1c_latent`.
4. **CIF JSON round-trip preserves `state_history` as a list of dicts and deserialises back to `YearSnapshot` instances.** The failure mode is lossy dataclass serialisation — pinned by `test_year_snapshot_serialisation.py::test_json_round_trip_preserves_year_and_continuous_keys`.
5. **`advance_one_year` on an unordered call sequence (year 3 then year 2) raises instead of silently prepending.** The spec's year-monotonic invariant must be defended — pinned by `test_engine.py::test_advance_one_year_raises_on_backward_year`.

---

## File Structure

### New files

| path | responsibility |
|---|---|
| `clinosim/modules/longitudinal/__init__.py` | Public API re-export: `advance_one_year`, `state_at`, `initial_snapshot`, `YearSnapshot` |
| `clinosim/modules/longitudinal/snapshot.py` | `YearSnapshot` dataclass + `yearsnapshot_from_dict` deserialiser |
| `clinosim/modules/longitudinal/patterns/__init__.py` | Pattern registry: `PATTERN_REGISTRY: dict[str, PatternHandler]` |
| `clinosim/modules/longitudinal/patterns/ar1.py` | `AR1Spec` + `step(prev, rng, spec, context) -> float` + `initial(rng, spec, context) -> float` |
| `clinosim/modules/longitudinal/loader.py` | `AttributeSpec` pydantic model + `load_attribute_specs() -> dict[str, AttributeSpec]` (lru_cached) + DAG topo sort |
| `clinosim/modules/longitudinal/engine.py` | `advance_one_year(person, year, year_rng) -> YearSnapshot`, `state_at(person, when) -> YearSnapshot`, `initial_snapshot(person, year, init_rng) -> YearSnapshot` |
| `clinosim/modules/longitudinal/README.md` | Module overview, 11-section canonical format |
| `clinosim/locale/shared/longitudinal/hba1c_trajectory.yaml` | Phase 1 attribute yaml (ar1 pattern, calibrated params + source citations) |
| `clinosim/locale/shared/longitudinal/README.md` | Catalog + authoring guide |
| `tests/modules/longitudinal/__init__.py` | Empty |
| `tests/modules/longitudinal/test_year_snapshot_serialisation.py` | `YearSnapshot` round-trip |
| `tests/modules/longitudinal/test_ar1_step_math.py` | AR(1) stationary mean / variance / clamp |
| `tests/modules/longitudinal/test_loader_dependency_sort.py` | DAG topo sort + cycle detection |
| `tests/modules/longitudinal/test_state_at_lookup.py` | year lookup semantics + boundary cases |
| `tests/modules/longitudinal/test_engine.py` | `advance_one_year` + `initial_snapshot` + idempotency + backward-year guard |
| `tests/modules/longitudinal/test_hba1c_physiological_bounds.py` | RBC-lifespan smoothness ≤1% per 60d on 1000-seed sweep + non-DM has no hba1c key |
| `tests/integration/test_longitudinal_engine_integration.py` | p=50 cohort end-to-end + mid-sim scope entry |
| `tests/integration/test_hba1c_trajectory_in_cif.py` | CIF HbA1c lab series AR(1) correlation + mean reversion |

### Modified files

| path | change |
|---|---|
| `clinosim/types/population.py` | PersonRecord: remove `glycemic_trajectory: dict[int, float]` field; add `state_history: list[YearSnapshot]` field (default empty list) |
| `clinosim/types/patient.py:141` | Remove `glycemic_control: float \| None` from PatientProfile — no longer per-patient state |
| `clinosim/modules/population/engine.py` | PersonRecord initialisation: delete `glycemic_trajectory={}`; initialise `state_history=[]` (seeding happens at first `advance_one_year`) |
| `clinosim/modules/population/aging.py` | Delete `_advance_glycemic_trajectory` and `_GLYCEMIC_ICDS`; `advance_population` calls `longitudinal.engine.advance_one_year(person, year, pass_rng)` at the end of each year |
| `clinosim/modules/patient/activator.py` | Remove `_glycemic_control_at_year`; remove `hba1c_from_glycemic_control` import; stage-string path at ~460 reads `state_at(person, as_of_year).continuous["hba1c"]`; delete per-encounter `glycemic_control` assignment at ~531 |
| `clinosim/modules/physiology/engine.py:322-324` | Remove the chronic-condition `glycemic_control` pull-up (now sourced via state_at); keep `hba1c_from_glycemic_control` as internal helper for protocol override |
| `clinosim/modules/physiology/engine.py:918-946` | HbA1c emit: if `state.glycemic_control is not None` (protocol override), use `hba1c_from_glycemic_control`; else read `state_at(person, encounter_dt).continuous["hba1c"]`. Add +N(0, 0.20) measurement noise overlay. |
| `clinosim/modules/output/cif_writer.py` | No code change — `asdict(patient_record)` serialises `state_history` through dataclass asdict automatically. Verify by test. |

### Fixture regeneration (housekeeping)

Fixtures that pin HbA1c values or `glycemic_control`-derived outputs. Regenerated in Task 12 as `pytest --regenerate-fixtures` or by hand:

- `tests/fixtures/*.json` — grep for `"HbA1c"`, `"glycemic_control"`, `"hba1c"`.
- FHIR goldens in `tests/e2e/` fixtures — grep for the same.

---

## Task Breakdown

### Task 1: `YearSnapshot` dataclass + CIF-friendly serialisation

**Files:**
- Create: `clinosim/modules/longitudinal/snapshot.py`
- Test: `tests/modules/longitudinal/test_year_snapshot_serialisation.py`

**Interfaces:**
- Consumes: nothing (foundation)
- Produces: `YearSnapshot(year: int, continuous: dict[str, float], chronic_stages: dict[str, str], new_complications: list[str], med_additions: list[str], med_removals: list[str])`; `yearsnapshot_from_dict(d: dict) -> YearSnapshot`

- [ ] **Step 1: Write the failing tests**

Add `test_year_snapshot_default_init_has_empty_dicts_and_lists`, `test_year_snapshot_asdict_roundtrips_through_json`, `test_json_round_trip_preserves_year_and_continuous_keys` (Review Focus item 4), `test_from_dict_tolerates_missing_optional_keys` to `tests/modules/longitudinal/test_year_snapshot_serialisation.py`. Each test's assertions use the exact fields and types the snapshot spec in §4.1 names.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/modules/longitudinal/test_year_snapshot_serialisation.py -v`
Expected: FAIL with "module clinosim.modules.longitudinal not found" or "YearSnapshot not defined"

- [ ] **Step 3: Implement `YearSnapshot` dataclass + `yearsnapshot_from_dict` in `clinosim/modules/longitudinal/snapshot.py`**

Dataclass with `@dataclass` decorator; fields exactly as the spec §4.1 names them, with `field(default_factory=...)` for the mutable ones. `yearsnapshot_from_dict` tolerates missing keys (defaults to empty).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/modules/longitudinal/test_year_snapshot_serialisation.py -v`
Expected: PASS all 4 tests

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/longitudinal/snapshot.py tests/modules/longitudinal/
git commit -s -m "feat(longitudinal): add YearSnapshot dataclass + serialisation"
```

---

### Task 2: AR(1) pattern math

**Files:**
- Create: `clinosim/modules/longitudinal/patterns/__init__.py`, `clinosim/modules/longitudinal/patterns/ar1.py`
- Test: `tests/modules/longitudinal/test_ar1_step_math.py`

**Interfaces:**
- Consumes: `numpy.random.Generator`
- Produces: `AR1Spec` pydantic model carrying `phi`, `sigma`, `mean_reversion_target`, `clamp`, `latent_name`, `initial.distribution.{kind,mu,sigma,clamp}`; `step(prev: float, rng: Generator, spec: AR1Spec) -> float`; `initial(rng: Generator, spec: AR1Spec) -> float`

- [ ] **Step 1: Write the failing tests**

Add to `tests/modules/longitudinal/test_ar1_step_math.py`:
- `test_step_mean_reverts_toward_target` — 10000-step chain from an off-target start converges to within 0.1 of `mean_reversion_target`.
- `test_step_stationary_variance_matches_closed_form` — stationary variance after 10000 steps is within 5% of `sigma² / (1 − phi²)`.
- `test_step_clamp_enforced_on_both_tails` — a step that would exceed `clamp[1]` returns `clamp[1]`; same for `clamp[0]`.
- `test_initial_lognormal_shape_matches_spec` — 10000 draws from `initial` have median within 0.1 of `exp(mu)` and 95th percentile within 0.2 of `exp(mu + 1.645*sigma)`.
- `test_step_zero_phi_is_pure_noise` — with `phi=0`, successive step draws have autocorrelation near 0.
- `test_step_phi_one_is_random_walk` — with `phi=1` and no mean reversion, the step is `prev + N(0, sigma)` (verify by expectation of `step(5.0, rng, spec) - 5.0` across many draws).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/modules/longitudinal/test_ar1_step_math.py -v`
Expected: FAIL with import errors

- [ ] **Step 3: Implement `AR1Spec`, `step`, `initial` in `clinosim/modules/longitudinal/patterns/ar1.py`**

`AR1Spec` is a pydantic BaseModel with the fields the yaml body declares. `step` applies `h_next = phi * prev + (1 - phi) * target + sigma * rng.standard_normal()`, then clamps. `initial` draws from `lognormal(mu, sigma)`, then clamps.

Create `patterns/__init__.py` with `PATTERN_REGISTRY: dict[str, Any] = {"ar1": {"spec": AR1Spec, "step": step, "initial": initial}}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/modules/longitudinal/test_ar1_step_math.py -v`
Expected: PASS all 6 tests

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/longitudinal/patterns/ tests/modules/longitudinal/test_ar1_step_math.py
git commit -s -m "feat(longitudinal): add AR(1) pattern math + spec"
```

---

### Task 3: `AttributeSpec` loader + DAG topological sort

**Files:**
- Create: `clinosim/modules/longitudinal/loader.py`
- Create: `clinosim/locale/shared/longitudinal/README.md` (minimal; full version in Task 13)
- Test: `tests/modules/longitudinal/test_loader_dependency_sort.py`

**Interfaces:**
- Consumes: `patterns.PATTERN_REGISTRY` (Task 2)
- Produces: `AttributeSpec` (pydantic model wrapping the common frontmatter + the pattern-specific body); `load_attribute_specs() -> dict[str, AttributeSpec]` (lru_cached); `topological_order(specs: dict[str, AttributeSpec]) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Add to `tests/modules/longitudinal/test_loader_dependency_sort.py`:
- `test_topological_order_respects_depends_on` — specs `{"a": depends=[], "b": depends=["a"]}` → order `["a", "b"]`.
- `test_topological_order_cycle_raises` — `{"a": depends=["b"], "b": depends=["a"]}` → `ValueError` with cycle members listed.
- `test_topological_order_missing_dependency_raises` — `{"b": depends=["a"]}` with no `a` → `ValueError("unknown dependency 'a' in attribute 'b'")`.
- `test_loader_validates_pattern_discriminator` — a yaml with `pattern: unknown` fails with `ValueError` naming registered patterns.
- `test_loader_validates_required_frontmatter_fields` — yaml missing `attribute_id` fails pydantic validation.

Use `tmp_path` fixtures with ad-hoc yaml files; monkeypatch `loader._LONGITUDINAL_DIR` to the tmp_path to isolate from real yaml.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/modules/longitudinal/test_loader_dependency_sort.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `AttributeSpec`, `load_attribute_specs`, `topological_order` in `clinosim/modules/longitudinal/loader.py`**

`AttributeSpec` has the common frontmatter (`attribute_id`, `pattern`, `depends_on`, `clinical_scope`) plus a `body: AR1Spec | MarkovSpec | EventSpec` discriminated union (Phase 1: only `AR1Spec`). `load_attribute_specs` globs `clinosim/locale/shared/longitudinal/*.yaml`, parses each, builds the dict. `topological_order` is a Kahn-style sort with explicit cycle / unknown-dep errors.

Create `clinosim/locale/shared/longitudinal/README.md` as a 10-line stub naming the catalog and pointing to the spec; the full authoring guide lands in Task 13.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/modules/longitudinal/test_loader_dependency_sort.py -v`
Expected: PASS all 5 tests

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/longitudinal/loader.py clinosim/locale/shared/longitudinal/README.md tests/modules/longitudinal/test_loader_dependency_sort.py
git commit -s -m "feat(longitudinal): add AttributeSpec loader + DAG topo sort"
```

---

### Task 4: Engine — `advance_one_year`, `state_at`, `initial_snapshot`

**Files:**
- Create: `clinosim/modules/longitudinal/engine.py`
- Create: `clinosim/modules/longitudinal/__init__.py`
- Test: `tests/modules/longitudinal/test_engine.py`, `tests/modules/longitudinal/test_state_at_lookup.py`

**Interfaces:**
- Consumes: `YearSnapshot` (Task 1), pattern functions via `PATTERN_REGISTRY` (Task 2), `load_attribute_specs` + `topological_order` (Task 3), `PersonRecord` (`clinosim.types.population`)
- Produces:
  - `advance_one_year(person: PersonRecord, year: int, year_rng: np.random.Generator) -> YearSnapshot` — mutates `person.state_history` by appending; returns the new snapshot
  - `state_at(person: PersonRecord, when: datetime | date | int) -> YearSnapshot` — `when` resolves to a year (int) or `when.year`; raises `IndexError` on empty history or out-of-range year
  - `initial_snapshot(person: PersonRecord, year: int, init_rng: np.random.Generator) -> YearSnapshot` — year is the sim-start year for pre-existing persons; appends to `state_history`; raises if already has a snapshot

- [ ] **Step 1: Write the failing tests (`test_engine.py` + `test_state_at_lookup.py`)**

Engine tests:
- `test_initial_snapshot_populates_hba1c_for_dm_person` — person with chronic E11 → `state_history[0].continuous["hba1c"]` present and within clamp.
- `test_initial_snapshot_omits_hba1c_for_non_dm_person` — person without E11/E10 → `state_history[0].continuous` has no `"hba1c"` key.
- `test_advance_one_year_appends_and_returns_snapshot` — a person with `state_history=[s0]` → `advance_one_year(..., year=s0.year+1, ...)` appends `s1`, returns `s1`.
- `test_advance_one_year_applies_ar1_step` — synthetic spec with `phi=1, sigma=0, target=0, clamp=[-inf,inf]` → `s1.continuous["hba1c"] == s0.continuous["hba1c"]`.
- `test_advance_one_year_raises_on_duplicate_year` — calling twice on the same year raises `ValueError`.
- `test_advance_one_year_raises_on_backward_year` (Review Focus 5) — `advance_one_year(person, year=5)` when `state_history[-1].year == 7` raises `ValueError`.
- `test_advance_one_year_requires_non_empty_state_history` — no initial snapshot → raises `ValueError`.
- `test_mid_sim_scope_entry_starts_hba1c_latent` (Review Focus 3) — a person without E11 at year 0 → `state_history[0].continuous` has no `"hba1c"`; add E11 to chronic_conditions, call `advance_one_year(year=1)` → `state_history[1].continuous["hba1c"]` present.

state_at tests:
- `test_state_at_resolves_integer_year` — `state_at(person, 2023)` returns the snapshot with `year==2023`.
- `test_state_at_resolves_datetime_year_component` — `state_at(person, datetime(2023,6,15))` returns the same snapshot.
- `test_state_at_raises_on_empty_state_history` — `IndexError` with message naming the person_id.
- `test_state_at_raises_on_out_of_range` — year before first snapshot's year or after last → `IndexError`.
- `test_year_boundary_encounters_resolve_to_correct_snapshot` (Review Focus 1) — a December-31 encounter resolves to year y; a January-1 encounter next year resolves to year y+1.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/modules/longitudinal/test_engine.py tests/modules/longitudinal/test_state_at_lookup.py -v`
Expected: FAIL

- [ ] **Step 3: Implement engine in `clinosim/modules/longitudinal/engine.py`**

`initial_snapshot` and `advance_one_year` share a helper that, for each attribute in topological order, checks `clinical_scope` against the person's chronic_conditions and age, then calls the pattern's `initial` or `step` respectively, writes the result into the new `YearSnapshot`. Scope eval reads `person.chronic_conditions` for base-code prefix match (e.g. `"E11"` matches `"E11.9"`, `"E11.21"`) and `person.age` adjusted to year under consideration against `requires_age_band`.

`state_at` dispatches on the `when` type: `int` → lookup by year; `datetime`/`date` → `.year` component.

Create `__init__.py` re-exporting `advance_one_year`, `state_at`, `initial_snapshot`, `YearSnapshot`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/modules/longitudinal/test_engine.py tests/modules/longitudinal/test_state_at_lookup.py -v`
Expected: PASS all tests

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/longitudinal/engine.py clinosim/modules/longitudinal/__init__.py tests/modules/longitudinal/test_engine.py tests/modules/longitudinal/test_state_at_lookup.py
git commit -s -m "feat(longitudinal): add engine (advance_one_year + state_at + initial_snapshot)"
```

---

### Task 5: `hba1c_trajectory.yaml` + end-to-end loader integration

**Files:**
- Create: `clinosim/locale/shared/longitudinal/hba1c_trajectory.yaml`
- Test: `tests/modules/longitudinal/test_hba1c_physiological_bounds.py`

**Interfaces:**
- Consumes: Task 3 loader, Task 2 AR1Spec, Task 4 engine
- Produces: a single `hba1c` attribute spec loaded into `load_attribute_specs()`

- [ ] **Step 1: Write the failing tests**

Add to `tests/modules/longitudinal/test_hba1c_physiological_bounds.py`:
- `test_hba1c_yaml_loads_as_ar1_spec` — `load_attribute_specs()["hba1c"].pattern == "ar1"`.
- `test_hba1c_params_match_calibration` — assert exact pinned values (`phi=0.75`, `sigma=0.40`, `mean_reversion_target=7.3`, `per_encounter_noise.sigma=0.20`, lognormal `mu=1.95`, `sigma=0.17`, clamps).
- `test_hba1c_trajectory_respects_rbc_lifespan_bound` — on 1000 seeds, each simulating a 5-year DM patient and sampling two encounters within 60 days each year, less than 1% of 60-day pairs show `|Δ| > 1.0%`.
- `test_non_dm_patient_has_no_hba1c_in_state_history` (Review Focus 2) — person with no E11/E10 in chronic_conditions → `state_history[0].continuous` has no `"hba1c"` after `initial_snapshot`.
- `test_pediatric_person_has_no_hba1c_in_state_history` — person with E11 but age=10 (below `requires_age_band[0]=18`) → `state_history[0].continuous` has no `"hba1c"`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/modules/longitudinal/test_hba1c_physiological_bounds.py -v`
Expected: FAIL (yaml missing)

- [ ] **Step 3: Create `clinosim/locale/shared/longitudinal/hba1c_trajectory.yaml`**

Pin values verbatim from the calibration artefact. Include the full `source:` list from the spec §4.2.1 example (DCCT/EDIC, ADVANCE, ACCORD, UKPDS, Wu 2023, ADA 2024) plus the PubMed / NEJM URLs from the pre-work artefact.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/modules/longitudinal/test_hba1c_physiological_bounds.py -v`
Expected: PASS all 5 tests

- [ ] **Step 5: Commit**

```bash
git add clinosim/locale/shared/longitudinal/hba1c_trajectory.yaml tests/modules/longitudinal/test_hba1c_physiological_bounds.py
git commit -s -m "feat(longitudinal): add HbA1c AR(1) trajectory yaml with literature-calibrated params"
```

---

### Task 6: `PersonRecord.state_history` + Layer-1 initialisation

**Files:**
- Modify: `clinosim/types/population.py`
- Modify: `clinosim/modules/population/engine.py`
- Modify: `clinosim/types/patient.py` (field removal)
- Test: `tests/unit/test_population_demographics.py` (extend existing or add new file)

**Interfaces:**
- Consumes: Task 4 engine `initial_snapshot`
- Produces: `PersonRecord.state_history: list[YearSnapshot]` field (removes `glycemic_trajectory`); `PatientProfile.glycemic_control` field removed

- [ ] **Step 1: Write the failing tests**

Add new tests to `tests/unit/test_population_demographics.py`:
- `test_person_record_has_state_history_field` — `PersonRecord(...).state_history == []`.
- `test_person_record_no_longer_has_glycemic_trajectory` — `hasattr(PersonRecord, "glycemic_trajectory") is False`.
- `test_patient_profile_no_longer_has_glycemic_control` — `hasattr(PatientProfile, "glycemic_control") is False`.
- `test_generate_population_seeds_state_history_for_dm_person` — a generated person with E11 chronic has `state_history[0].continuous["hba1c"]` populated.
- `test_generate_population_leaves_state_history_empty_for_non_dm` — a generated person without E11/E10 has `state_history[0].continuous` empty (no `"hba1c"`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_population_demographics.py -v -k "state_history or glycemic"`
Expected: FAIL

- [ ] **Step 3: Modify `clinosim/types/population.py`**

Remove `glycemic_trajectory: dict[int, float] = field(default_factory=dict)`. Add `state_history: list[YearSnapshot] = field(default_factory=list)` imported from `clinosim.modules.longitudinal.snapshot`.

Modify `clinosim/types/patient.py:141`: delete the `glycemic_control: float | None = None` line and its docstring comment.

Modify `clinosim/modules/population/engine.py`: at the PersonRecord construction site (line 791), remove `glycemic_trajectory={}` from kwargs. Immediately after construction, call `longitudinal.engine.initial_snapshot(person, base_year, person_init_rng)` with a sub-RNG derived from `aging_sub_seed(person_id, base_year, "longitudinal:init")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_population_demographics.py -v -k "state_history or glycemic"`
Expected: PASS all 5 tests

- [ ] **Step 5: Commit**

```bash
git add clinosim/types/population.py clinosim/types/patient.py clinosim/modules/population/engine.py tests/unit/test_population_demographics.py
git commit -s -m "feat(longitudinal): seed PersonRecord.state_history at Layer-1 init; retire glycemic_control fields"
```

---

### Task 7: Aging driver integration — `advance_population` wires `advance_one_year`

**Files:**
- Modify: `clinosim/modules/population/aging.py` — remove `_advance_glycemic_trajectory`, `_GLYCEMIC_ICDS`; call `longitudinal.engine.advance_one_year` from `advance_population`
- Create: `tests/modules/longitudinal/test_aging_integration.py`

**Interfaces:**
- Consumes: Task 4, Task 6
- Produces: a `advance_population(year)` call that leaves each alive DM person with `state_history` growing by one snapshot per year

- [ ] **Step 1: Write the failing tests**

Add to the test file:
- `test_advance_population_appends_snapshot_per_alive_dm_person` — mini registry with 3 persons (1 DM E11, 1 non-DM, 1 dead) → after `advance_population(year=y+1)`, DM person has `len(state_history) == 2`, non-DM has `len == 1` (no `hba1c` key added), dead has `len == 1` (unchanged).
- `test_advance_glycemic_trajectory_is_gone` — `hasattr(aging, "_advance_glycemic_trajectory") is False`.
- `test_aging_driver_calls_engine_in_topological_order` — monkeypatch `longitudinal.engine.advance_one_year` to record call order; verify it is called after other aging passes finish for a given person.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/modules/longitudinal/test_aging_integration.py -v`
Expected: FAIL (behaviour not wired)

- [ ] **Step 3: Modify `clinosim/modules/population/aging.py`**

- Delete `_advance_glycemic_trajectory` function and `_GLYCEMIC_ICDS` constant.
- In `advance_population`'s per-person inner loop (after `_condition_reactive_mortality`), add:
  ```python
  longitudinal_rng = np.random.default_rng(aging_sub_seed(person.person_id, year, "longitudinal"))
  longitudinal.engine.advance_one_year(person, year, longitudinal_rng)
  ```
- Remove `_advance_glycemic_trajectory` from the `for pass_fn in (...)` tuple at line ~1070.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/modules/longitudinal/test_aging_integration.py -v`
Expected: PASS all 3 tests

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/population/aging.py tests/modules/longitudinal/test_aging_integration.py
git commit -s -m "feat(longitudinal): wire advance_one_year into advance_population; retire _advance_glycemic_trajectory"
```

---

### Task 8: Physiology HbA1c emit — read from `state_at`

**Files:**
- Modify: `clinosim/modules/physiology/engine.py:322-324` (remove PatientProfile `glycemic_control` pull-up branch) and `:918-946` (HbA1c emit path)
- Test: `tests/unit/test_physiology.py` (extend)

**Interfaces:**
- Consumes: Task 4 `state_at`
- Produces: HbA1c emitted value derived from `state_at(person, encounter_dt).continuous["hba1c"]` + measurement noise; protocol override still works via `state.glycemic_control`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_physiology.py`:
- `test_hba1c_emit_reads_from_state_history_when_no_protocol_override` — build a mini `person` with `state_history=[snapshot(year=2023, continuous={"hba1c": 9.1})]`, call the HbA1c emit for a 2023 encounter → emitted value within `9.1 ± 3*0.20` (3-sigma band for the per-encounter noise).
- `test_hba1c_emit_honours_protocol_override` — same person, but `state.glycemic_control = 0.3` → emitted value matches `hba1c_from_glycemic_control(0.3)` within the measurement-noise band, NOT the state_history value.
- `test_hba1c_emit_fallback_when_state_history_absent` — non-DM person (no `"hba1c"` in `continuous`) → emit path does not add `"HbA1c"` to `labs` (no key). Verifies the non-emit case cleanly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_physiology.py -v -k "hba1c"`
Expected: FAIL (new behaviour not wired)

- [ ] **Step 3: Modify `clinosim/modules/physiology/engine.py`**

- Delete lines 322-324 (the chronic-condition `glycemic_control` pull-up).
- At the HbA1c emit site (near line 946):
  ```python
  if state.glycemic_control is not None:
      labs["HbA1c"] = hba1c_from_glycemic_control(state.glycemic_control)
  else:
      snapshot = longitudinal.engine.state_at(person, encounter.admission_datetime)
      latent = snapshot.continuous.get("hba1c")
      if latent is not None:
          labs["HbA1c"] = float(np.clip(
              latent + rng.standard_normal() * HBA1C_MEASUREMENT_NOISE_SD,
              HBA1C_CLAMP_MIN, HBA1C_CLAMP_MAX,
          ))
      # else: no HbA1c lab emitted (non-DM; no latent)
  ```
- Add constants `HBA1C_MEASUREMENT_NOISE_SD = 0.20`, `HBA1C_CLAMP_MIN = 4.0`, `HBA1C_CLAMP_MAX = 15.0` sourced from `hba1c_trajectory.yaml` via loader (or hard-coded with a docstring citing the yaml as source of truth, if the loader is awkward to import at module scope).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_physiology.py -v -k "hba1c"`
Expected: PASS all 3 tests

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit -s -m "feat(longitudinal): physiology HbA1c emit reads from state_history; protocol override preserved"
```

---

### Task 9: Activator stage-string migration (line 460)

**Files:**
- Modify: `clinosim/modules/patient/activator.py` — remove `_glycemic_control_at_year`; replace stage-string generation at ~460
- Test: `tests/unit/test_activator_dm_stage.py` (new file)

**Interfaces:**
- Consumes: Task 4 `state_at`
- Produces: stage string for E11/E10 chronic conditions is `f"HbA1c {state_at_year.continuous['hba1c']:.1f}%"`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_activator_dm_stage.py`:
- `test_e11_stage_string_reads_from_state_history` — person with `state_history=[snapshot(year=2023, continuous={"hba1c": 9.1})]`, call `_build_chronic_conditions(..., as_of_year=2023)` → the E11 ChronicCondition's `stage == "HbA1c 9.1%"`.
- `test_e11_stage_string_tracks_year` — person with `state_history=[s0(hba1c=7.5), s1(hba1c=10.2)]`, call with `as_of_year=s0.year` → `stage == "HbA1c 7.5%"`; call with `as_of_year=s1.year` → `stage == "HbA1c 10.2%"`.
- `test_glycemic_control_at_year_helper_is_gone` — `hasattr(activator, "_glycemic_control_at_year") is False`.
- `test_non_dm_chronic_still_builds_without_hba1c` — person with I48 chronic → stage string generation does not raise.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_activator_dm_stage.py -v`
Expected: FAIL (helper still exists; stage reads from random)

- [ ] **Step 3: Modify `clinosim/modules/patient/activator.py`**

- Delete `_glycemic_control_at_year` function.
- Delete the `from clinosim.modules.physiology.engine import hba1c_from_glycemic_control` import.
- At the stage-string site (~460), replace with:
  ```python
  if code_base in ("E11", "E10"):
      snapshot = longitudinal.engine.state_at(person, as_of_year)
      hba1c = snapshot.continuous.get("hba1c")
      if hba1c is not None:
          stage = f"HbA1c {hba1c:.1f}%"
      else:
          stage = ""  # pre-adult DM onset; no latent yet
  ```
- Delete the `glycemic_control=glycemic_control` kwarg at line 531.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_activator_dm_stage.py -v`
Expected: PASS all 4 tests

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/patient/activator.py tests/unit/test_activator_dm_stage.py
git commit -s -m "feat(longitudinal): activator DM stage string reads from state_history"
```

---

### Task 10: Remaining `glycemic_control` call-site sweep

**Files:**
- Modify: any file still referencing `glycemic_control` outside of `PhysiologicalState` (which keeps the field as a transient protocol-override hook) and the retained `hba1c_from_glycemic_control` helper in physiology
- Modify: `clinosim/modules/physiology/engine.py:918-919` — `is_diabetic` check should source from `state_at(person).continuous.get("hba1c") is not None` or from chronic_conditions E11/E10 directly, not `state.glycemic_control`
- Test: a sweep test asserting the field is retired where expected

**Interfaces:**
- Consumes: Tasks 6-9 cumulative
- Produces: `grep -rn "glycemic_control" clinosim/` returns only `PhysiologicalState.glycemic_control`, `hba1c_from_glycemic_control` helper, `protocol.chronic_glycemic_control`, and the inpatient.py protocol-override assignment — no `PatientProfile` or `PersonRecord` references remain

- [ ] **Step 1: Write the failing test (sweep)**

Create `tests/unit/test_glycemic_control_retirement.py`:
- `test_patient_profile_has_no_glycemic_control_attribute` (duplicate of Task 6 but kept here as regression guard).
- `test_person_record_has_no_glycemic_trajectory_attribute` (same).
- `test_remaining_glycemic_control_references_are_whitelisted` — run `subprocess.run(["grep", "-rn", "glycemic_control", "clinosim/"], ...)` and parse. Every hit must be in a whitelist of allowed locations: `types/clinical.py:PhysiologicalState`, `modules/physiology/engine.py:hba1c_from_glycemic_control` and its constants, `modules/disease/protocol.py:chronic_glycemic_control`, `simulator/inpatient.py` protocol-override assignment. Unexpected hits fail the test with the file:line printed.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_glycemic_control_retirement.py -v`
Expected: FAIL on `test_remaining_glycemic_control_references_are_whitelisted` listing surviving references (grep from Task 6-9 start state before cleanup)

- [ ] **Step 3: Clean up remaining references**

Grep + patch each surviving reference. Modify `physiology/engine.py:918` from:
```python
is_diabetic = has_diabetes or state.glycemic_control is not None
```
to:
```python
snapshot = longitudinal.engine.state_at(person, encounter.admission_datetime) if person.state_history else None
has_hba1c_latent = snapshot is not None and "hba1c" in snapshot.continuous
is_diabetic = has_diabetes or state.glycemic_control is not None or has_hba1c_latent
```

If any other call-site still references the removed fields, migrate it analogously (lab emit paths, narrative paths — grep covers all of them).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_glycemic_control_retirement.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add clinosim/ tests/unit/test_glycemic_control_retirement.py
git commit -s -m "chore(longitudinal): retire PatientProfile.glycemic_control / PersonRecord.glycemic_trajectory sweep"
```

---

### Task 11: End-to-end integration test — cohort HbA1c trajectory

**Files:**
- Create: `tests/integration/test_longitudinal_engine_integration.py`
- Create: `tests/integration/test_hba1c_trajectory_in_cif.py`

**Interfaces:**
- Consumes: Tasks 1-10 cumulative
- Produces: end-to-end verification that a p=50 US seed=42 2y cohort produces per-encounter HbA1c lab series on DM patients that respect the AR(1) smoothness bound and the mean-reversion target

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_longitudinal_engine_integration.py`:
- `test_mini_cohort_dm_patients_have_state_history_populated` — p=50 US seed=42 1y cohort → every alive E11 person has `state_history` with length ≥ 1 and `continuous["hba1c"]` populated.
- `test_mini_cohort_non_dm_patients_have_empty_hba1c` — same cohort, non-E11/E10 persons have no `"hba1c"` key.

`tests/integration/test_hba1c_trajectory_in_cif.py`:
- `test_p50_dm_patient_hba1c_series_within_rbc_bound` — generate p=50 US seed=42 2y cohort via `clinosim.simulator.cli`'s simulate call (programmatic), load CIF, extract HbA1c lab series for every E11 patient; for every 60-day pair within a patient, assert `|Δ| ≤ 2.0` (slacker than the 1.0 bound to allow 3-sigma noise but tight enough to fail if AR(1) is broken).
- `test_p50_cohort_hba1c_mean_reverts_to_target` — cohort-level mean HbA1c across all DM patients × all encounters is within 0.5 of `mean_reversion_target=7.3`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_longitudinal_engine_integration.py tests/integration/test_hba1c_trajectory_in_cif.py -v`
Expected: FAIL if any earlier task has an incorrectly-wired edge; PASS otherwise — this is the integration gate.

- [ ] **Step 3: Fix any surfaced integration bugs**

Likely surfaces: scope-gate off-by-one on age band, state_at year-component dispatch bug, measurement-noise constant imported from the wrong place. Fix at the task that owns the broken behaviour; re-run.

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/unit tests/integration -x --ignore=tests/e2e -q`
Expected: all pass (count will match the current master baseline + the new tests added in Tasks 1-11; no pre-existing tests fail).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_longitudinal_engine_integration.py tests/integration/test_hba1c_trajectory_in_cif.py
git commit -s -m "test(longitudinal): add p=50 cohort integration + CIF trajectory validation"
```

---

### Task 12: Fixture regeneration + `scripts/reproduce.sh` validation + cohort audit

**Files:**
- Modify: any pinned-value test fixture file pre-existing in `tests/` that contains an `HbA1c` or `glycemic_control` value
- Create: `scratchpad/longitudinal_phase1_audit.md` (session-local, not committed) — p=500 US seed=42 5y cohort audit confirming no 60-day pair `|Δ| > 1.0 %`
- Modify: `CHANGELOG.md` under `## [Unreleased]`

**Interfaces:**
- Consumes: Tasks 1-11
- Produces: a clean `reproduce.sh` CI gate; all pre-existing fixtures aligned with new output

- [ ] **Step 1: Grep for every fixture / golden file touched by HbA1c migration**

Run:
```bash
grep -rln -E '"HbA1c"|hba1c|glycemic_control' tests/ --include='*.json' --include='*.yaml' --include='*.ndjson'
```

For each hit, regenerate the fixture from the new master. Document the before/after in commit messages.

- [ ] **Step 2: Run `scripts/reproduce.sh`**

Run: `scripts/reproduce.sh`
Expected: byte-identical reproducibility across the two runs for both US and JP cohorts.

- [ ] **Step 3: Cohort audit on p=500 US seed=42 5y**

Run:
```bash
clinosim simulate -o scratchpad/longitudinal_phase1_cohort \
  --country US -p 500 -s 42 --start 2021-01-01 --end 2025-12-31 \
  --format cif
```

Write a short audit script that extracts HbA1c series per DM patient and counts 60-day pairs with `|Δ| > 1.0 %`. Record the count + distribution in `scratchpad/longitudinal_phase1_audit.md`.

Target: < 1 % of 60-day pairs out-of-bound.

- [ ] **Step 4: Update CHANGELOG**

Add a `Changed` entry under `## [Unreleased]` describing the HbA1c trajectory migration + the retirement of `PersonRecord.glycemic_trajectory` and `PatientProfile.glycemic_control`.

- [ ] **Step 5: Commit**

```bash
git add tests/ CHANGELOG.md
git commit -s -m "chore(longitudinal): regenerate fixtures for Phase 1 HbA1c trajectory"
```

---

### Task 13: Module READMEs + canonical 11-section doc

**Files:**
- Create: `clinosim/modules/longitudinal/README.md` (full)
- Create: `clinosim/modules/longitudinal/README.ja.md`
- Modify: `clinosim/locale/shared/longitudinal/README.md` (expand from Task 3 stub)

**Interfaces:**
- Consumes: all prior tasks (documentation describes the shipped module)
- Produces: canonical 11-section module README per `docs/CONTRIBUTING-modules.md`

- [ ] **Step 1: Write `clinosim/modules/longitudinal/README.md`**

Follow the canonical 11-section layout: Purpose, Scope, Public API, Internal structure, Data files, Determinism, Testing, Caller integration, Related modules, Change log, Future phases.

- [ ] **Step 2: Write JA README mirror.**

- [ ] **Step 3: Expand `clinosim/locale/shared/longitudinal/README.md`**

Catalog listing (currently: `hba1c_trajectory.yaml`), authoring guide (common frontmatter + pattern bodies), review workflow (domain expert reads one file).

- [ ] **Step 4: Verify docs reflect reality**

Run: `grep -l 'TODO\|TBD\|FIXME' clinosim/modules/longitudinal/ clinosim/locale/shared/longitudinal/`
Expected: no hits.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/longitudinal/README.md clinosim/modules/longitudinal/README.ja.md clinosim/locale/shared/longitudinal/README.md
git commit -s -m "docs(longitudinal): add canonical READMEs for module + data"
```

---

## Final gate — PR authoring

After Task 13:

- Push branch, open PR with body summarising the spec and the Phase 1 scope boundary (migrates HbA1c, Markov / event patterns deferred).
- Link to issue #1695 (closes), reference META #1694.
- CI runs full suite + `scripts/reproduce.sh`.
- On green CI, `gh pr merge --rebase --delete-branch`.
