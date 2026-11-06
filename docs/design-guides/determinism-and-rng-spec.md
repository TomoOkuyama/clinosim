# Determinism and random numbers — specification

Status: **normative**. Every change that draws a random number, derives a seed, reads a clock, or adds a step that runs inside the simulation follows this document. A change that cannot follow it updates this document in the same PR, with the reason.

Japanese counterpart: [`determinism-and-rng-spec.ja.md`](determinism-and-rng-spec.ja.md). Background and the cross-platform story: [`docs/development/reproducibility.md`](../development/reproducibility.md). The summary in [`implementation-rules.md`](implementation-rules.md) §3 points here.

## 1. Principles

1. **Same input, same output.** A run is a pure function of its configuration (population, seed, dates, country, provider). The output is byte-identical across runs, machines and CPU architectures (AD-16).
2. **One generator factory.** Every random generator is created by `clinosim.determinism.default_rng`. Nothing else creates a numpy generator, and nothing uses Python's `random` module or global RNG state.
3. **One seed derivation.** Every seed comes from `clinosim/seeding.py`: a registered module offset or a named seed function. Seeds never come from Python's `hash()`, the clock, object ids or iteration order of a set.
4. **Local streams.** Each decision draws from a stream keyed by the entity it concerns (patient, encounter, order, day). A change to one decision therefore cannot shift the draws of another (AD-59).
5. **No clock on the generation path.** Simulated time comes from the configuration and the simulated events. The wall clock is read only for run metadata (§5).
6. **Every rule has a guard.** Each rule below names the test that enforces it; a rule without one is listed in §8.

## 2. Drawing random numbers

| Rule | Canonical code | Guard |
|---|---|---|
| A generator is created only by `determinism.default_rng(seed)`. It is a proxy over numpy's PCG64. It draws `normal` / `standard_normal` / `beta` / `exponential` with bit-reproducible algorithms (`mpmath` at fixed precision) and delegates every other method (`random`, `integers`, `choice`, ...) to numpy, whose integer arithmetic is already identical everywhere. | `clinosim/determinism.py` (`default_rng`, `normal`, `beta`, `exponential`) | `tests/unit/test_rng_through_determinism_2529.py` (no `np.random.default_rng` outside `determinism.py`), `tests/unit/test_determinism.py` |
| Python's `random` module is not imported on the generation path. | — | `tests/unit/test_determinism_spec_guards.py::test_no_stdlib_random` |
| A probability vector read from YAML goes through `normalize_probabilities(p, fallback="raise")` before `rng.choice(p=...)`. | `clinosim/modules/_shared.py::normalize_probabilities` | `implementation-rules.md` §4 (review) |
| A choice that needs no stream (a stable "random-looking" pick of a nurse, a side, a time) uses a hash, not a generator. These helpers draw nothing, so adding them never shifts a stream. | `determinism.sha_quantile` / `sha_bernoulli` / `sha_weighted_choice`; `seeding.rendezvous_pick` / `id_hashes`; `seeding.morse_fall_history_unit` | `tests/unit/test_seeding.py` |

## 3. Deriving seeds

| Rule | Canonical code | Guard |
|---|---|---|
| A module's stream is `derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS[<module>], <entity key>)`. The offset is registered once, as hex ASCII of the module name (4 bytes), unique across modules. `identity` and `microbiology` keep their grandfathered decimal values. | `seeding.derive_sub_seed`, `seeding.ENRICHER_SEED_OFFSETS` | `tests/unit/test_enricher_seed_offsets.py`, `tests/unit/test_seeding.py` |
| A simulation phase's stream is `derive_phase_rng(master_seed, PHASE_<name>, key)`. The phase salts are registered in `_PHASE_OFFSETS`. | `seeding.derive_phase_rng`, `PHASE_LIFE_EVENT` / `PHASE_INPATIENT_SIM` / `PHASE_READMISSION` / `PHASE_OUTPATIENT_CAL` / `PHASE_ED_VISIT` | `tests/unit/test_seeding.py` |
| A recurring per-entity stream has a named seed function, so every caller derives it the same way. | `seeding.py`: `panel_specimen_seed` (lab panel), `individual_lab_seed` (lab order), `chronic_medication_seed`, `discharge_prescription_seed`, `ambulatory_visit_length_seed`, `issue939_procedure_seed`, `chronic_augment_sex_seed`, `chronic_isolated_seed`, `longitudinal_event_seed`, `perinatal_delivery_seed`, `chemotherapy_regimen_seed`, `daily_output_seed`, `text_seed` | `tests/unit/test_seeding.py` (formula pinned for the lab seeds) |
| A seed is computed with `hashlib.sha256`, never with `hash()` (salted per process by `PYTHONHASHSEED`). | `seeding.derive_sub_seed`, `seeding.text_seed` | `tests/unit/test_determinism_spec_guards.py::test_no_builtin_hash_call` |

## 4. Keeping changes RNG-neutral

A new feature, field, module or fix must not move the draws of anything it does not change. In order of preference:

1. **Draw nothing.** Derive the value from data already generated, or from a hash (§2 last row). Examples: the side of a paired imaging study (`imaging_laterality`), the nurse giving a placed-order dose (`placed_order_mar.stable_nurse`), the Morse fall-history item.
2. **Draw from a new local stream.** Key a sub-seed by the entity (`derive_sub_seed(seed, offset, f"{encounter_id}:{specimen}:{n}")`). Register a new offset for a new module.
3. **Never insert a draw into an existing stream**, reorder its draws, or make a draw conditional on new data. All three shift every later draw of that stream. They also shift every patient cached behind it (F4 memoization of the person cache).

When a change must alter outcomes (a model change), the PR states which streams moved and shows the cohort effect (§6).

## 5. Clocks

| Rule | Canonical code | Guard |
|---|---|---|
| Generation reads no wall clock. Simulated times come from `--start` / `--end` and the events. A dataclass default for a required time is the sentinel `_UNSET_DATETIME` (1970-01-01), never `datetime.now()`. | `clinosim/types/clinical.py`, `clinosim/types/encounter.py` (`_UNSET_DATETIME`) | `tests/unit/test_wallclock_sentinel_defaults.py`, `tests/unit/test_fhir_bundle_no_wallclock.py` |
| The wall clock is read only for run metadata: the Bulk Data manifest `transactionTime`, `_generator_metadata.json`, the CIF metadata `generation_timestamp`, the narrative version's `generated_at`, CLI defaults (`--end` defaults to today) and reports. These values are not part of the byte-diff. | the files allowed in the guard | `tests/unit/test_determinism_spec_guards.py::test_wall_clock_only_in_run_metadata` |

## 6. Verifying

- `bash scripts/reproduce.sh` reproduces a run and compares sha256 of every output file.
- A change that should be output-neutral shows a CIF and FHIR byte-diff of 0 against master built from the same base commit (US and JP).
- A change that alters outcomes compares cohorts from the same base commit. The PR lists the changed paths (e.g. `orders[].result`, `microbiology`) and the number of patients that differ, so an unexpected stream shift is visible.

## 7. Iteration order and caches

- A walk over a set or dict that feeds a draw is sorted first. The order of an unsorted set depends on string hashing.
- The return value of an `@lru_cache` loader is shared; it is never mutated (`implementation-rules.md` §3).
- Enricher order (`stage` + `order`) and the `NarrativePass` walk order are fixed; changing them is a stream change (§4).

## 8. Gaps

None known. A new exception is added here with its guard allow-list entry.
