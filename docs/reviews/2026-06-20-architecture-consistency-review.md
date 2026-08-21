# Architecture consistency review — clinosim

## 1. Overview

Overall, the clinosim architecture is healthy. AD-16 (determinism), AD-17 (CIF-only output), and AD-18 (Pydantic/dataclass separation) are broadly followed correctly; stdlib `random` usage is zero (DET-8), reverse dependencies from `types/` to `modules/` are zero (TYP-10), and the English-first principle is fully enforced across all 10 code systems (CODES-1). The bulk of issues are "concept application gaps", not "concept violations" — the baseline rules are correct, but there are scattered places where they are not mechanically enforced.

Top 3 refactors by value/effort:

1. **DET-4 (`_prev_diet` function-object global state)** — the only confirmed `high` violation that actually breaks AD-16. Shares stale state within the process and, combined with the deterministic patient IDs (`FORCED-0001` etc.) of `run_forced`, causes cross-test contamination. The fix is small — localize to a variable.
2. **FA-4 (ghost field `*_diagnosis_name`)** — `csv_adapter.py:94,96` and `narrative_generator.py:94` read a field that does not exist on CIF and always return the empty string. A `high` with real damage (the CSV diagnosis-name column is always empty) that also violates AD-30. Resolve by replacing with `code_lookup()` calls.
3. **Extract a shared sub-seed helper (DET-2/EXT-4)** — an identical `_sub_seed` implementation is copy-pasted across 3 modules, and there is no test guarding against OFFSET collisions. Scattering the AD-16 core logic is a determinism-assurance risk. Resolve with a shared helper + an OFFSET-uniqueness test.

---

## 2. Module / plugin consistency assessment

### `clinosim/types/` organization and public API boundary

Uniform points:
- The AD-18 Pydantic/dataclass separation has 0 violations inside `types/` (TYP-9): only `config.py` uses `BaseModel`; everything else is `@dataclass`.
- Layer separation is clean — zero `from clinosim.modules` / `from clinosim.simulator` inside `types/*.py`, and internal imports are acyclic (TYP-10).

Drift points:
- **Shared runtime types defined inside modules** — `PersonRecord`/`LifeEvent`/`HospitalizationSummary` (`population/engine.py:34,81,18`), `StaffMember`/`StaffRoster` (`staff/engine.py:17,31`), `ProcedureRecord`/`RehabSession` (`procedure/engine.py:17,426`), `HospitalState` (`facility/hospital_state.py:17`). All are typed-imported cross-module yet not under `types/` (MOD-2,3,4,6 / TYP-2). Violates CLAUDE.md "All types defined in `clinosim/types/`".
- **Untyped `list` fields on CIF** — `intake_output_records`/`adl_assessments`/`nursing_risk_assessments`/`immunizations` at `output.py:52-55` are declared as bare `list` even though the element types are already in `encounter.py:177-232` and could be imported (TYP-3). On the other hand, `procedures`/`rehab_sessions` cannot be typed until the element types are moved (currently in `modules/`), because typing them today would introduce a reverse dependency.
- **Name leakage from star imports** — 7 star imports in `types/__init__.py` leak `Any`/`BaseModel`/`dataclass`/`datetime` into the `clinosim.types` namespace (TYP-6). Only `identity.py`/`microbiology.py` define `__all__`.
- **Dead code** — `DiagnosticAccuracyConfig` (`clinical.py:94`) has no reference anywhere in the codebase (TYP-7).

### `clinosim/modules/` structure and dependency conventions

Uniform points:
- `observation/engine.py` is the reference example of a "pure function engine" with zero cross-module imports and all context passed as arguments (MOD-13 / OBS-1).

Drift points:
- **17 out of 18 `__init__.py` files are 0 bytes** — only `identity/__init__.py` (378 bytes, defines `__all__`) has a formal API surface. The rest are imported directly from `.engine` (MOD-1 / TYP-1). CLAUDE.md's "Public API surface: only what's exported in module `__init__.py`" is de facto dead letter.
- **Private-function cross-module import** — `patient/activator.py:13` imports `_sample_given_name` (underscore = private) from `population/engine.py:589` (MOD-7 / TYP-5). Encapsulation violation. The function is really a sampler over locale name data; it belongs under `locale/`.
- **Non-uniform dependency-declaration heading** — only `identity/README.md` uses the English `## Dependencies`; the other 17 use `## 依存関係` (MOD-12). The content exists, but CI cannot parse it.
- `DiseaseProtocol(BaseModel)` at `disease/protocol.py:15` is a config type used cross-module but is tightly coupled to the loader and YAML directory, making it borderline (MOD-5 / TYP-2 partly). Exporting via `disease/__init__.py` is more realistic than moving.

### Extension point registries (AD-55..58)

Drift points (3 registries, 3 different designs):
- **3 different builtin-loading patterns** — bundle builder uses a static list literal (`fhir_r4_adapter.py:1119`), output adapter uses lazy `_ensure_builtins()` (`adapter.py:46`), enricher uses an explicit call `register_builtin_enrichers()` (`enrichers.py:64`, `engine.py:103`) (EXT-2).
- **3 different idempotency strategies** — adapter dict overwrite (last-wins, `adapter.py:43`), enricher name skip (first-wins, `enrichers.py:49`), builder identity-check (`if builder not in`, `fhir_r4_adapter.py:1140`) (EXT-3). The builder identity-check is the most fragile: two callables with identical intent can be double-registered.
- **No metadata type on builder** — the `Enricher` dataclass (`enrichers.py:35-40`) has name/stage/order/enabled, but `_BUNDLE_BUILDERS` is a plain callable list (EXT-1).
- **`module_enabled()` is unused in production** — defined at `types/config.py:128-130` but has zero call sites. The enricher's `enabled` lambda uses direct attribute checks (`enrichers.py:79,93,106`), and the gating advertised by AD-56 is not wired up (EXT-5).
- **`register_bundle_builder()` is not exported from the public surface** — only defined at `fhir_r4_adapter.py:1138`. Asymmetric with `register_output_adapter`/`register_enricher` (EXT-7 partly).
- **Prefix inconsistency** — `_build_nursing_observations`/`_build_immunizations` (`fhir_r4_adapter.py:870,1065`) coexist with 13 other `_bb_*` (EXT-6).
- **Enricher registry uses a list (O(n) lookup)** — `_ENRICHERS: list` (`enrichers.py:43`). Performance is irrelevant with 3 entries, but first-wins skip blocks test override (EXT-8).

### Output adapters (FHIR R4 + CSV)

Uniform points:
- JP localization dicts are correctly isolated to `fhir_r4_adapter.py`, and the enrichment path is language-neutral (AD-44 compliant). `hospital_course_extractor`/`narrative_generator`/`llm_service` have zero references to JP dicts (FA-6).

Drift points:
- **Monolith** — `fhir_r4_adapter.py` is 3542 lines, 54 functions, 15+ resource types, and ~14 JP dicts collected in one file (FA-1 / MOD-9). The AD-56 registry itself is correctly implemented.
- **Wrap-contract exception** — `_build_vital_observations` is the only builder that returns dicts already wrapped by `_entry()` (`fhir_r4_adapter.py:2636,2685,2736`); all other `_build_*` return raw resource dicts. `_bb_vitals` unwraps to reconcile, but this is a trap: adding a 4th vital would double-wrap it (FA-3).
- **Duplicate procedure-display lookup** — `_procedure_display` (`fhir_r4_adapter.py:1577`) tries a single code, while `_resolve_procedure_name` (`hospital_course_extractor.py:288`) tries all 3 code fields. The FHIR adapter caller (`:3050-3056`) passes only `procedure_code`, so when only `procedure_code_jp` is set the display is empty (FA-5).
- **CSV adapter ignores country** — `convert_cif_to_csv` has no country argument (`csv_adapter.py:13`), and `CsvAdapter.convert` drops `ctx.country` (`adapters_builtin.py:17-20`). The FHIR adapter passes `country=ctx.country` (FA-9).
- **Vital LOINC display hardcode drift** — the inline displays in `_vital_map` (`fhir_r4_adapter.py:2524-2531`) do not match `loinc.yaml` (e.g., `8867-4` = `脈拍` vs loinc.yaml `心拍数`; `2708-6` = `Oxygen saturation` vs `Oxygen saturation in Arterial blood`) (FA-8).

### YAML / data-driven patterns

Uniform points:
- The code-lookup architecture is healthy — `code_lookup` consistently resolves ICD/LOINC/SNOMED/RxNorm display, and `load_code_mapping()` is applied consistently (CODES-1).
- The scientific parameters (BIOLOGICAL_CV etc.) in `observation/engine.py` are correctly inline Python (OBS-1).

Drift points:
- **Encounter protocol is not Pydantic-validated** — `encounter/protocol.py:15-38` returns raw `dict[str,Any]` and `except Exception: pass` (`:35`) swallows YAML parse errors. Asymmetric with `DiseaseProtocol(BaseModel)` at `disease/protocol.py`; violates AD-18. 46 YAMLs are unvalidated (ENC-1).
- **HL7 URI hardcode** — ~25-28 HL7/LOINC/SNOMED/UCUM URIs are embedded in `fhir_r4_adapter.py` as string literals and bypass `get_system_uri()` (URI-1 / FA-2 / CODES-4). In particular, `observation-category` is hardcoded in 5 places (`:1628,2422,2545,2656,2697`) despite being registered in `_BUILTIN_URIS`; UCUM is hardcoded in 16 places with zero `get_system_uri('ucum')` calls.
- **Display-table dispersion and duplication**:
  - `_DEPT_DISPLAY_JA` (19 entries, `:428-448`) vs `_DEPARTMENT_DISPLAY` (10 entries, `:2141-2152`) — a language-split of the same concept. The EN table is missing 9 departments, producing a silent-fallback bug in US output (DUP-1).
  - `_MED_TERMS_JA` (~149 entries, `:54-203`) and `_MED_CATEGORY_JA` are inline Python, but drug names are YAML-driven (DUP-2).
  - `CONDITION_NAMES` (`activator.py:60-108`) duplicates the display from `code_lookup()` (DUP-3).
  - `_CONDITION_SHORT_NAME` (`:1780-1833`) — clinical shorthand table. However, CLAUDE.md explicitly directs its use, and it is a different concept from authoritative ICD text (DUP-4 partly; moving is not recommended).
- **Dead import / stale docstring** — `load_terminology` is imported at `fhir_r4_adapter.py:17` but unused, and the target YAML has already been migrated (LOC-2 / CODES-3). `locale/loader.py:4-11` docstring references `japan/` (actually `jp/`) and a deleted terminology file (CODES-11).
- **Loader bypass** — `activator.py:384-390` reads `chronic_medications.yaml` directly with `yaml.safe_load`, bypassing `load_chronic_medications()` (with lru_cache) at `locale/loader.py:89` (LOC-1).
- **R69 fallback hardcode** — `diagnosis/engine.py:193,207` returns `'Illness, unspecified'` as a literal, bypassing `_display()` in the same file. This displays in English on JP output (DIAG-1).
- **JP interpretation inconsistency** — `determine_flag()` is not passed a locale range (`inpatient.py:604,1615`, `outpatient.py:178`, `emergency.py:146`), so on JP output `Observation.interpretation` (H/L) is computed against the US default while `referenceRange` shows the JCCLS value (OBS-3).

### Data generation & determinism (AD-16 / AD-17)

Uniform points:
- Every venue simulator builds CIF via return-based construction (`inpatient.py:402`, `outpatient.py:254`, `emergency.py:228`), with zero direct writes to a shared collection (DET-7).
- Zero use of stdlib `random` (DET-8).

Drift points:
- **`_prev_diet` function-object global state** (`inpatient.py:761,774-776`) — actually breaks AD-16 (DET-4; see overview for detail).
- **`generate_observations` wrapper is not extracted** — the same logic is duplicated in 4 places (`inpatient.py:580-612`, `:1611-1623`, `outpatient.py:156-187`, `emergency.py:124-155`). Only the inpatient main path branches on specimen-rejection / hemolysis; ED patients silently never lose a specimen — a clinical inconsistency (DET-1, TODO.md:323).
- **Identity sub-seed is not keyed** — `assign.py:33` uses a single shared RNG with `master_seed + offset`. The other 3 enrichers use a per-patient sha256-keyed RNG (DET-3).
- **Baseline fallback dict drift** — `outpatient.py:149-154` (WBC 6500, CRP 0.5, HbA1c 6.5) vs `emergency.py:107-109` (WBC 7500, CRP 1.0, HbA1c 5.6) (DET-6, TODO.md:310).
- **DES engine unwired** — `_handle_outpatient`/`_handle_ed_visit` are empty stubs (`des_engine.py:300-307`), and `DESEngine` is not referenced from engine.py (DET-5). Doc gap only.

### codes + locale separation

Uniform points (good):
- English-first invariant has 0 gaps across all 10 systems / 1004 codes, enforced by tests (CODES-1).
- Terminology-file migration into codes/ is complete, with zero remaining display text in locale (CODES-2).
- The diagnosis code coverage test covers all 3 sources + a WHO format guard (CODES-5).

Drift points:
- **Fabricated display for RxNorm CUI 18631** — `code_mapping_drug.yaml:8-9` maps both Amoxicillin/Clavulanate and Azithromycin to `18631`, and `rxnorm.yaml:68-70` gives both a fictional concatenated display (CODES-7, `high`). Contradicts the NLM authoritative source.
- **No coverage test for non-diagnosis codes** — RxNorm/YJ/CPT/K-codes/CVX have no emittable-code test equivalent to diagnosis (CODES-6). The current state is clean but this could not have caught CODES-7.
- Minor: RBC is present in the JP map but missing from the US map (CODES-9; intentional if not emitted on US), and the `drug_ja` branch is unreachable in production (CODES-10).

---

## 3. Refactor candidates (priority-ordered)

Confirmed / partly-confirmed only. Ordered by value/effort. Concept-fit = whether the fix clearly aligns with CLAUDE.md / AD principles.

| id | Target (file:line) | Problem | Recommendation | Effort | Risk | Concept-fit |
|---|---|---|---|---|---|---|
| DET-4 | `inpatient.py:761,774-776` | `_prev_diet` accumulates process-lifetime global state on the function object (AD-16 violation) | Localize inside `_run_daily_loop`; remove `getattr` | small | low (golden diff only if contamination-dependent) | ◎ AD-16 core |
| FA-4 | `csv_adapter.py:94,96`; `narrative_generator.py:94` | Reads a nonexistent `*_diagnosis_name`, always empty (AD-30 violation, real damage) | Replace with `code_lookup(system, code, lang)`; add imports | small | CSV golden refresh required | ◎ AD-30 |
| CODES-7 | `code_mapping_drug.yaml:8-9`; `rxnorm.yaml:68-70` | CUI 18631 shared across 2 drugs, fabricated display | Look up correct CUIs via NLM rxnav; register separately | small | US MedicationRequest golden refresh required | ◎ authoritative source |
| LOC-2 / CODES-3 | `fhir_r4_adapter.py:17` | Dead import `load_terminology` | Remove the import | small | none | ○ |
| LOC-1 | `activator.py:384-390` | Reads `chronic_medications.yaml` bypassing the loader | Replace with `load_chronic_medications()` | small | none | ○ canonical loader |
| DIAG-1 | `diagnosis/engine.py:193,207` | Literal-return of R69, bypassing `_display()` (English on JP output) | Replace with `_display('R69')` | small | JP golden (R69 is rare) | ○ language-neutral |
| CODES-11 | `locale/loader.py:4-11` | Docstring references `japan/` + a deleted file | Update the docstring | small | none | ○ |
| TYP-8 | `types/__pycache__/narrative*.pyc` | Stale pyc without source (gitignored) | Local cleanup with `find -delete` | small | none | ○ |
| TYP-3 | `output.py:52-55` | 4 fields are bare `list` (types exist in encounter.py) | Import from `encounter.py` and type them | small | none (annotation only) | ◎ type-location |
| TYP-6 | `types/__init__.py` | Star imports leak stdlib/Pydantic names | Add `__all__` to 5 files | small | none | ○ |
| EXT-6 | `fhir_r4_adapter.py:870,1065` | `_build_*` prefix mixed with `_bb_*` | Rename to `_bb_` + update test imports | small | tests only | ○ |
| EXT-7 | `output/__init__.py` | `register_bundle_builder` not exported | Re-export from `__init__.py` (no file split) | small | none | ○ AD-56 |
| DET-2 / EXT-4 | `immunization/enricher.py:19`; `nursing_enricher.py:28`; `microbiology.py:39` | `_sub_seed` copy-pasted 3 times, no OFFSET-collision test | Extract `derive_sub_seed` into `helpers.py` + uniqueness test | small | low (golden unchanged if formula preserved) | ◎ AD-16 |
| MOD-7 / TYP-5 | `activator.py:13`; `population/engine.py:589` | Cross-module import of private `_sample_given_name` | Promote to public in `locale/names.py` | small | none (pass rng argument) | ◎ encapsulation |
| OBS-3 | `inpatient.py:604,1615`; `outpatient.py:178`; `emergency.py:146` | On JP output, interpretation is computed against the US default (inconsistent with referenceRange) | Pass `reference_ranges=load_reference_ranges(country)` | small | JP H/L flag golden refresh required | ◎ JP compliance |
| DET-6 | `outpatient.py:149-154`; `emergency.py:107-109` | WBC/CRP/HbA1c baseline fallback drift | Single `_BASELINE_LAB_NORMALS` in `observation/engine.py` | small | golden only on fallback path | ○ |
| EXT-5 | `enrichers.py:79,93,106`; `config.py:128` | `module_enabled()` not wired | Route enricher `enabled` through `module_enabled(default=...)` | small | none (default preserved) | ◎ AD-56 |
| EXT-8 / EXT-3 | `enrichers.py:43,49` | Enricher registry is list + first-wins | Convert to `dict[str, Enricher]` (last-wins + warning) | small | none (integer order unchanged) | ○ |
| ENC-1 | `encounter/protocol.py:15-38` | Not Pydantic-validated; errors are swallowed | `EncounterConditionProtocol(BaseModel)` + `extra='allow'` | small | none (validation wrapper) | ◎ AD-18 |
| MOD-4 / TYP-2 | `staff/engine.py:17,31` | `StaffMember`/`StaffRoster` inside module | Move to `types/staff.py`; re-export via `__init__` first | small | none (managed import breakage) | ◎ type-location |
| MOD-6 | `facility/hospital_state.py:17` | `HospitalState` inside module | Move to `types/facility.py` | small | none | ◎ type-location |
| MOD-5 | `disease/protocol.py:15` | `DiseaseProtocol` inside module (loader-coupled) | Export via `disease/__init__.py` (moving is optional) | small | none | ○ borderline |
| DET-3 | `assign.py:33,40,42` | Identity sub-seed is not keyed | Per-member `derive_sub_seed(.., person_id/household_id)` | small | JP identity golden refresh (intentional) | ○ |
| FA-3 | `fhir_r4_adapter.py:2636,2685,2736` | Only the vital builder returns wrapped dicts | Remove `_entry()` and return raw; extend `_bb_vitals` | small | none (NDJSON unchanged) | ○ |
| FA-5 | `fhir_r4_adapter.py:3056` | Procedure display references 1 code only | Delegate to `_resolve_procedure_name(proc, lang)` | small | golden on jp-only-code cases | ○ DRY |
| FA-9 | `csv_adapter.py:13`; `adapters_builtin.py:17` | CSV ignores `ctx.country` | Add `country='US'` argument (linked with FA-4) | small | diagnoses.csv only | ○ |
| DUP-3 | `activator.py:60-108`; `outpatient.py:230` | `CONDITION_NAMES` duplicates `code_lookup` | Replace with `code_lookup('icd-10-cm', code, 'en')` | small | display strings become longer forms | ○ AD-30 |
| CODES-6 | (new test) | No coverage test for non-diagnosis codes | Add `test_nondiagnosis_code_coverage.py` | small | none (additive) | ◎ |
| DET-1 | `inpatient.py:580`; `outpatient.py:156`; `emergency.py:124` | `generate_observations` wrapper duplicated 4×; pre-analytical branch inconsistency | Extract `_resolve_lab_orders(.., pre_analytical=)` into helpers.py | medium | golden risk (RNG draw order) | ◎ DRY |
| URI-1 / FA-2 / CODES-4 | `fhir_r4_adapter.py` (~25-28 places) | HL7/LOINC/SNOMED/UCUM URI hardcode | Extend `_BUILTIN_URIS` + replace with `get_system_uri()`; add URI assert test first | medium | golden unchanged if URI values unchanged | ◎ URI rule |
| MOD-2 / TYP-2 | `population/engine.py:18,34,81` | `PersonRecord` etc. inside module | Move to `types/population.py` (re-export first) | medium | none (many imports) | ◎ type-location |
| MOD-3 | `procedure/engine.py:17,426` | `ProcedureRecord`/`RehabSession` inside module | Move to `types/procedure.py`; type CIF; move adapter to typed access | medium | verify CIF serialize path | ◎ type-location |
| DUP-1 | `fhir_r4_adapter.py:428,2141` | Dept display tables are language-split; EN missing 9 | Consolidate into `locale/shared/department_display.yaml` | small | US dept display golden | ○ |
| DUP-2 | `fhir_r4_adapter.py:32-203` | `_MED_TERMS_JA` / `_MED_CATEGORY_JA` inline | Move to `locale/shared/med_terms_ja.yaml` | small | JP med text golden | ○ |
| MOD-11 | `fhir_r4_adapter.py:1780-1833` | `_CONDITION_SHORT_NAME` duplicates codes/ | Add a `short_name` field to codes YAML + `lookup(field=)` | medium | Condition.code.text golden refresh | ○ (in tension with DUP-4) |
| MOD-1 / TYP-1 | all `__init__.py` | 17/18 are empty; no formal API surface | Re-export boundary-crossing types/functions via `__init__` | medium | none (caller migration is staged) | ◎ |
| MOD-12 | 17 READMEs | Non-uniform dependency heading (`## 依存関係`) | Standardize to `## Dependencies` + CI lint | small | none (doc-only) | ○ |
| EXT-1 / EXT-3 | `fhir_r4_adapter.py:1119,1140` | No builder metadata; identity-check fragile | Add `available_builders()` + name-based dedup (defer BundleBuilder type until a use case) | small | none | ○ (avoid over-engineering) |
| EXT-2 | 3 registries | 3 different builtin loading patterns | Convert enricher to lazy `_ensure_builtins()` (optional) | small | low | △ intentional difference |
| TYP-7 | `clinical.py:94` | `DiagnosticAccuracyConfig` dead code | Remove (or wire into `SimulatorConfig`) | small | none if removed | ○ |
| FA-8 | `fhir_r4_adapter.py:2524-2531` | Vital LOINC display drift vs loinc.yaml | Move to `_loinc_coding()` (after verifying `loinc.yaml` `ja`) | small | vital display golden refresh | ○ (requires authoritative check) |
| FA-1 / MOD-9 | `fhir_r4_adapter.py` (3542 lines) | Monolith | Staged extraction starting with `_localization.py`, e2e after each extraction | large | high (golden) | ○ (not urgent) |

**Recommended defer (including reject)**: MOD-8 (`DiagnosisCandidate`/`DifferentialDiagnosis` are genuinely module-local with no cross-module leak — preemptive relocation is rejected). PHY-1 (physiology conditional branches cannot be YAML-encoded without a DSL, and coefficient changes destroy all goldens — hold at 15 conditions). OBS-2 (the 4 qualitative tests are stable; YAML-encode once past ~8). DET-5 (DES integration is a separate feature). DUP-4 (clinical shorthand is a separate concept from authoritative ICD text; hold until a second adapter appears). CODES-9 / CODES-10 (minor; pending scope confirmation).

---

## 4. Commonalization review

Only commonalizations that align with the concept AND actually reduce duplication.

### 4.1 Sub-seed derivation helper (DET-2 / EXT-4)
- **Current state**: the identical 3-line `_sub_seed(master, key)` implementation is copy-pasted in `immunization/enricher.py:19` (offset `0x494D`), `nursing_enricher.py:28` (`0x4E55`), and `microbiology.py:39` (`_encounter_seed`, `770_077`). No OFFSET-collision test exists.
- **Shared API**: `clinosim/simulator/helpers.py`:
  ```
  def derive_sub_seed(master: int, module_offset: int, key: str) -> int
  ```
  The formula (`sha256(key.encode()).digest()[:6]` + offset) is **preserved exactly**. Each module passes its own OFFSET constant (unchanged).
- **Determinism / golden safety**: if the formula is unchanged including byte count, modulus, and endianness, the RNG stream is unchanged → goldens are unchanged. **First** write a unit test like `derive_sub_seed(42, 0x4E55, 'pid-1') == <precomputed>` and confirm green before removing each local copy. In addition, add a new test that "all registered OFFSETs are distinct". Leave the simple formula at `identity/assign.py:33` (no key hash) as-is (this is intentional in the 1-RNG/population-pass design).

### 4.2 Lab-order resolution wrapper (DET-1)
- **Current state**: the sequence order → canonical_lab_name → generate_lab_result → determine_flag → OrderResult → append is duplicated across 4 places. Only the inpatient main path branches on 2% specimen-rejection / 3% hemolysis; ED/outpatient do not (clinical inconsistency).
- **Shared API**: `clinosim/simulator/helpers.py`:
  ```
  def _resolve_lab_orders(orders, true_labs, patient, rng, *,
      hospital_state=None, hospital_ops=None, roster,
      country: str, pre_analytical: bool = False) -> list[OrderResult]
  ```
  `pre_analytical=True` only for the inpatient main path. Each venue passes its own rng → per-order draw order is unchanged. Adding `country` also solves OBS-3 (pass a locale range to `determine_flag`) at the same time.
- **Determinism / golden safety**: the pre-analytical branch is chance-gated continuation within the same order iteration, so it does not change existing draw counts. After extraction, diff goldens with `pytest -m e2e`. When you fold in the OBS-3 range injection, expect an intentional JP H/L flag golden refresh.

### 4.3 Registry helper / metadata (EXT-1 / EXT-3 / EXT-8)
- **Current state**: 3 registries differ in idempotency, loading, and storage. The builder identity-check is the most fragile.
- **Shared API**: full unification across the 3 registries is not needed (the semantic difference — last-wins = format override / first-wins = double-registration prevention — is intentional). Minimal fix:
  - Add `available_builders() -> list[str]` introspection to the bundle builder, and switch `register_bundle_builder` dedup from identity-based to name-based.
  - Convert enricher to `dict[str, Enricher]` (`run_stage` becomes `sorted(values, key=lambda e: (e.order, e.name))`); log a warning on name overwrite.
  - **Do not introduce `BundleBuilder` dataclass / `enabled` predicate until a concrete use case (country-gated builder that cannot gate internally) appears** — forcing a lambda on every existing `_bb_*` is pure churn.
- **Determinism / golden safety**: if the integer `order` is unchanged, the sort result is unchanged → goldens are unchanged. Builder list ordering affects FHIR entry order but is order-independent. Verify before/after with e2e.

### 4.4 Dept display / med terms YAML consolidation (DUP-1 / DUP-2)
- **Current state**: language-split Python dicts. The EN dept table is missing 9 (US silent bug).
- **Shared API**: `locale/shared/department_display.yaml` (`{key: {en, ja}}`) + `load_department_display()`; `locale/shared/med_terms_ja.yaml` + `load_med_terms_ja()` (lru_cache). The existing `drug_names_ja.yaml` is the model.
- **Safety**: display-only. Expect a US dept display (9 items) and JP med text golden refresh. CIF unchanged.

### 4.5 Things **not** to extract (besides sub-seed)
- Physiology coefficients (PHY-1) and observation scientific parameters (OBS-1) are correctly co-located — YAML-encoding only increases I/O dependency without maintainability gain, and any change to them requires code review anyway.

---

## 5. Already-good designs (maintain, propagate)

- **`observation/engine.py` pure-function engine** (MOD-13 / OBS-1) — zero cross-module imports; all context received as arguments. The reference example for other module refactors. Recommend explicitly citing it in CLAUDE.md as "an example of no cross-module deps".
- **Return-based CIF contribution** (DET-7) — every venue does `return CIFPatientRecord(...)` with zero direct writes to a shared collection. Fully AD-17 compliant.
- **Zero use of stdlib random** (DET-8) — no `import random`. Consider a `grep` pre-commit hook to prevent regression.
- **AD-18 Pydantic/dataclass separation** (TYP-9) — 0 violations inside `types/`.
- **Clean layer separation in `types/`** (TYP-10) — zero reverse dependencies to `modules/`/`simulator/`, internally acyclic. Preserve this invariant during type moves (MOD-2, 3, 4, 6).
- **English-first invariant** (CODES-1) — enforced across all 10 systems / 1004 codes via tests + fallback chain.
- **Terminology codes/ migration complete** (CODES-2).
- **Diagnosis code coverage test** (CODES-5) — 3 sources + WHO format guard. Extend the same pattern to RxNorm/YJ/CPT/K-codes/CVX via CODES-6.
- **Language-neutral isolation of the enrichment path** (FA-6 / AD-44) — JP dicts do not leak out of `fhir_r4_adapter.py`. Preserve this boundary during the FA-1 split (do not let extractor/narrative/llm_service import `_localization.py`).
- **AD-56 registry correctly implemented** — `register_bundle_builder` (`:1138`), `register_output_adapter`, and `register_enricher` allow extension without editing `_build_bundle`.

---

## 6. Recommended implementation order

### Phase 1 — golden-safe quick wins (can land as a single PR)
1. Dead code / cosmetic: LOC-2 / CODES-3 (remove dead import), CODES-11 (docstring), TYP-8 (pyc cleanup), TYP-7 (delete `DiagnosticAccuracyConfig`).
2. Loader normalization: LOC-1 (route via `load_chronic_medications`).
3. Type annotation only: TYP-3 (type CIF 4 fields), TYP-6 (add `__all__`).
4. Internal rename / re-export: EXT-6 (unify `_bb_`), EXT-7 (re-export `register_bundle_builder`), FA-3 (remove vital wrap — NDJSON unchanged).
5. Encapsulation: MOD-7 / TYP-5 (promote `_sample_given_name` to `locale/names.py`).
6. Validation wrapper: ENC-1 (`EncounterConditionProtocol` + `extra='allow'`).
→ After each step run `pytest -m unit`; run `pytest -x` at PR close.

### Phase 2 — determinism / correctness fixes (golden refresh expected, intentional)
7. **DET-4** (localize `_prev_diet`) — highest priority. Record diet-order counts via e2e first.
8. **Shared sub-seed helper** (DET-2 / EXT-4) — precomputed test first; confirm formula unchanged. Add OFFSET uniqueness test.
9. **FA-4 + FA-9 + DUP-3** (ghost field → `code_lookup`; inject country into CSV) — CSV golden refresh.
10. **CODES-7** (RxNorm CUI fix) — verify via NLM rxnav; US med golden refresh. Add **CODES-6** (non-diagnosis coverage test) simultaneously to prevent regression.
11. DIAG-1 (R69 `_display()`), OBS-3 (locale range injection — can merge with DET-1), DET-6 (baseline unification).

### Phase 3 — structural refactors (type-location / registry, staged PRs)
12. Type moves (one PR each, re-export first → switch engine import → migrate callers): MOD-4 (staff) → MOD-6 (facility) → MOD-2 (population) → MOD-3 (procedure). MOD-5 (disease) is `__init__` export only.
13. Run MOD-1 / TYP-1 (formal `__init__.py` API surface) in parallel with the type moves.
14. Registry helpers (EXT-1 / EXT-3 / EXT-8 — name-based dedup, enricher dict-ification, `available_builders()`); EXT-5 (wire `module_enabled`, keep default).
15. **DET-1** (extract `_resolve_lab_orders`) — verify RNG draw order via e2e diff.
16. URI-1 / FA-2 / CODES-4 (route URIs through `get_system_uri`; add assert test first).
17. DUP-1 / DUP-2 (YAML-encode dept/med terms); MOD-11 (move `short_name` into codes/ — separately decide between a codes/data sibling file and a locale placement, taking DUP-4 tension into account); FA-5 / FA-8 (unify procedure/vital display).

### Defer (separate feature branch / hold)
- **FA-1 / MOD-9** (split 3542 lines) — high golden risk. After phases 2/3 complete, staged extraction starting from `_localization.py` with e2e after each step. Not urgent.
- DET-3 (identity keyed sub-seed) — changes JP identity goldens; land as a solo PR with an announcement.
- DET-5 (DES integration), PHY-1 (physiology DSL), MOD-8 (preemptive move rejected), DUP-4 (until a second adapter appears), CODES-9 / 10 (pending scope confirmation).
- MOD-12 (unify README heading + CI lint) — doc-only; land whenever convenient.
