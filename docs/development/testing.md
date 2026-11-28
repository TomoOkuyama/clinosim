<!-- Extracted from `README.md` (Issue #568 PR A2). Update the pointer in README when this file's heading changes. -->

# Testing

```bash
source .venv/bin/activate

# All tests (unit ~1 min, integration ~30 min, e2e ~8 min)
pytest -x

# By category
pytest -m unit                   # Tests marked `unit` (~5200 cases; tests/unit/ holds ~5600 test functions, ~7700 collected cases)
pytest -m integration            # Cross-module (includes reproduce.sh gate)
pytest -m e2e                    # E2E + golden tests

# Coverage
pytest --cov=clinosim
```

### Reproducibility

clinosim guarantees **byte-identical output** for a given
`(seed, config, country, start, end, population)` tuple within a MINOR
release line — wall-clock / git-dependent metadata (`fhir_r4/manifest.json`,
`fhir_r4/_generator_metadata.json`, `cif/metadata.json`, narrative-pass
`manifest.json`) is expected to differ, everything else must match.

Verify at any time:

```bash
bash scripts/reproduce.sh
```

The script runs `clinosim simulate --format fhir` twice per locale
(US + JP by default; JP with `--allow-legacy`, so no JP-CLINS package is
needed) to two isolated temp directories, sha256s every
NDJSON + CIF JSON, and diffs the hash lists. Exit 0 = byte-identical,
exit 1 = determinism regression with the offending file(s) listed in
the diff. Environment variables `CLINOSIM_REPRO_COUNTRIES`,
`CLINOSIM_REPRO_POPULATION`, `CLINOSIM_REPRO_SEED`,
`CLINOSIM_REPRO_START`, `CLINOSIM_REPRO_END` override the defaults.

CI runs it on every push and PR through
`tests/integration/test_full_reproducibility.py` (integration job), and
the `reproducibility` job in `nightly.yml` runs it daily, so a
regression trips the merge gate before code lands.

### Refactoring proof (`scripts/refactor-diff.sh`)

A refactoring must not change any output, and it is proven only on a run in
which the moved code executed: a cohort of a few hundred patients can be
byte-identical without ever reaching a path that fires once per thousand
stays. Three pieces work together (Issue #3976):

- **Forced-scenario corpus** — `tests/refactor_corpus/scenarios.yaml`: one
  forced stay per path a refactoring may move (each complication action kind,
  the vasopressor start, the DKA transition, the hyperkalemia / AKI /
  renal-replacement / lactate responses, each discharge criterion, a
  hospital-acquired infection, the delivery modes, an ED admission), US and
  JP. It is built on `run_forced`; a complication is forced on a stated day
  with the test-only `ForcedScenario.force_complications`, which only
  `run_forced` reads. `tests/refactor_corpus/run_corpus.py` generates it (CIF,
  template narratives, FHIR R4, one directory per scenario).
- **Fired counters** — `clinosim/fired_counters.py`: one `count("<path>")`
  call where each such path acts. The counters draw no random number, are not
  written into CIF or FHIR, and are reset at the start of every run; the
  runner writes them to a JSON sidecar outside the output tree. Each scenario
  lists the paths it must fire (`expect`), and `run_corpus.py check` fails
  when one did not.
- **The comparison** — `scripts/refactor-diff.sh <base> <head>` checks out
  both commits in detached worktrees, generates the corpus and a US and a JP
  cohort (seed 42, population 200 by default and at most 300,
  2025-07-01..2026-06-30, CIF and FHIR) on each, compares every file (logs,
  `_generator_metadata.json` and the wall-clock keys of the metadata files
  excepted), prints the differences and the fired counters of both commits,
  and exits non-zero on any difference or on an expected path that did not
  fire on `<head>`.

```bash
scripts/refactor-diff.sh origin/master HEAD   # about 3 minutes on a laptop
```

The corpus definition and runner of `<head>` are run against both commits, so
both generate the same scenarios; `<base>` must contain the corpus (a base
without fired counters shows `-` in its counter columns). The CI workflow
`refactor-diff.yml` runs the script for every pull request labelled
`refactoring`, against the merge base. A refactoring PR names the paths it
moves and quotes their counts ("path X fired N times in the corpus, M in the
US cohort, K in the JP cohort, identical on both commits"); a path that fires
0 times is not proven, so add a scenario that fires it first.

---
