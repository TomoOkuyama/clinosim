# PR 1 — Lab-Observation coding strategy refactor: byte-identical verification

Date: 2026-07-25
Branch: `feat/lab-coding-strategy-pr1`
Baseline commit: `803bd4547d` (master, post-hotfix PR #394)
PR: TBD (Issue TBD)

## Purpose

Pin the byte-identical evidence for the JP-CLINS lab coding migration
PR 1 (strategy dispatcher refactor). This is a one-shot verification
that the strategy pattern refactor did not shift a single byte of
production FHIR NDJSON output for JP or US cohorts at p=100 seed=300.
Per session 67 workspace:5 memo, this evidence lives in a PR-specific
docs review rather than a recurring CI check — the verification is
whole-refactor-shape and does not need to fire on every subsequent PR.

## Baseline generation

Both cohorts generated on `master 803bd4547d` (before any PR 1 code
change) in parallel:

```
clinosim generate -p 100 -s 300 --country JP --format fhir-r4 -o output/jp_p100_s300_baseline_pr1
clinosim generate -p 100 -s 300 --country US --format fhir-r4 -o output/us_p100_s300_baseline_pr1
```

## After-PR1 generation

After the strategy refactor commit was applied (this PR's changes to
`clinosim/modules/output/_fhir_observations.py` +
`clinosim/modules/output/_lab_coding_strategy.py`), both cohorts
regenerated with identical flags:

```
clinosim generate -p 100 -s 300 --country JP --format fhir-r4 -o output/jp_p100_s300_after_pr1
clinosim generate -p 100 -s 300 --country US --format fhir-r4 -o output/us_p100_s300_after_pr1
```

## byte-identical evidence

### `Observation.ndjson` SHA-256

| cohort | baseline | after PR 1 | equal? |
|---|---|---|---|
| JP | `83933a25df4b9149a0e7460803096e15e3a83e22f518ac2206c8483f341bbfb8` | `83933a25df4b9149a0e7460803096e15e3a83e22f518ac2206c8483f341bbfb8` | ✅ |
| US | `ce6a9627296fbba7852a657870316573fce4ce72c4dea4dd4872e93e7a37778f` | `ce6a9627296fbba7852a657870316573fce4ce72c4dea4dd4872e93e7a37778f` | ✅ |

### `diff -qr` on the whole `fhir_r4/` directory

Both cohorts return empty `diff -qr` output (excluding `manifest.json`
and `_generator_metadata.json`, which carry generation timestamps and
are known to differ per invocation).

```
$ diff -qr output/jp_p100_s300_baseline_pr1/fhir_r4/ output/jp_p100_s300_after_pr1/fhir_r4/ | grep -v manifest.json | grep -v _generator_metadata.json
# (empty)

$ diff -qr output/us_p100_s300_baseline_pr1/fhir_r4/ output/us_p100_s300_after_pr1/fhir_r4/ | grep -v manifest.json | grep -v _generator_metadata.json
# (empty)
```

## Both dispatcher paths exercised

byte-identical alone is not sufficient — an unexercised path could
have a refactor bug that a hash comparison would miss because the path
never ran. This section pins that both `LabCodingKind` members active
in PR 1 (`LEGACY_JSLM` for JP, `LEGACY_LOINC` for US) were actually
dispatched during the after-PR1 generation.

### Observation `code.coding[].system` distribution (JP p=100 s=300 after PR 1)

| system | occurrences |
|---|---:|
| `urn:oid:1.2.392.200119.4.1005` (JSLM generic OID) | 2523 |
| `http://loinc.org` (LOINC secondary) | 2509 |

- All 2,523 lab Observations emit the JSLM OID primary coding →
  `LegacyJSLMStrategy.emit_codings` executed for every JP lab.
- 2,509 of those append a LOINC secondary → the JP-only dual-coding
  branch inside `LegacyJSLMStrategy.emit_codings` executed as well.

### Observation `code.coding[].system` distribution (US p=100 s=300 after PR 1)

| system | occurrences |
|---|---:|
| `http://loinc.org` (LOINC primary) | 1192 |

- All 1,192 US lab Observations emit a single LOINC coding →
  `LegacyLOINCStrategy.emit_codings` executed for every US lab.

## Axis baseline unchanged

`clinosim.eval.axes.jp_clins_lab_compliance.run` on the after-PR1 JP
cohort produces the same 3-metric shape as the pre-refactor baseline:

| Metric | value | outcome |
|---|---|---|
| CS 使用率 | 0/2509 = 0.0% | FAIL |
| Fixed display 一致率 | 0/0 = n/a | NA |
| 適用規則満足率 | 0/2509 = 0.0% | FAIL |

Denominator 2,509 matches the microbiology-excluded population from the
axis PR (session 67 T67-M1 scope), Metric 2 NA is the pkg-present
zero-slice-typed-coding state — none of the three metrics moved
because none of the strategies emit slice-typed codings in PR 1.

## Verification summary

| check | expected | actual |
|---|---|---|
| JP `Observation.ndjson` sha256 unchanged | equal | equal ✅ |
| US `Observation.ndjson` sha256 unchanged | equal | equal ✅ |
| JP `diff -qr` on `fhir_r4/` | empty (excl. metadata) | empty ✅ |
| US `diff -qr` on `fhir_r4/` | empty (excl. metadata) | empty ✅ |
| JP LEGACY_JSLM path exercised | ≥1 JSLM OID emit | 2523 ✅ |
| JP LOINC-secondary branch exercised | ≥1 LOINC emit on JP lab | 2509 ✅ |
| US LEGACY_LOINC path exercised | ≥1 LOINC emit on US lab | 1192 ✅ |
| axis 3-metric shape unchanged | 0/2509 / n/a / 0/2509 | matched ✅ |
| PR 1 invariant: `emit_localcode_coding` → None on every strategy | None × 5 strategies | None ✅ (unit test `test_pr1_invariant_emit_localcode_coding_returns_none`) |

## Non-goals for this verification

- **Not verified**: full test suite green (verified separately;
  3,244 unit tests pass after refactor + 18 new strategy tests).
- **Not verified**: strict integration under seed variation. Byte
  identity was checked only at seed 300; the refactor is a control
  flow no-op so seed sensitivity is not expected, but no other seed
  was measured because the refactor cannot introduce seed-dependent
  divergence by construction (no RNG touched).
- **Not verified**: US LOINC secondary + JP-only branches on cohorts
  larger than p=100. p=100 s=300 was chosen to keep the byte-identical
  check fast; the coding path is invariant to cohort size.
