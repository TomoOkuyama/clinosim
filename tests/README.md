# tests/ conventions

Anchor doc for `clinosim`'s test suite. Rules only — the rationale lives in
each linked follow-up. When a rule and this file disagree, this file wins.

## Directory layout — mirror `clinosim/`

The path under `tests/` mirrors the path under `clinosim/`.

| Test file                                | Covers                                |
| ---------------------------------------- | ------------------------------------- |
| `tests/unit/output/test_foo.py`          | `clinosim/modules/output/foo.py`      |
| `tests/unit/simulator/test_bar.py`       | `clinosim/simulator/bar.py`           |
| `tests/integration/test_baz_chain.py`    | multi-module chain in `clinosim/`     |

Top-level `tests/unit/*.py` is a legacy area (see Issue #567 layout sweep).
**New tests go under the mirrored subdirectory**: `tests/unit/modules/<module>/`
for `clinosim/modules/<module>/`, `tests/unit/<package>/` for the other
packages, `tests/integration/` for a multi-module chain. Do not add new files
to `tests/unit/` directly.

The guard `tests/unit/docs/test_test_layout_guard.py` enforces this. It
freezes today's number of flat `tests/unit/test_*.py` files and of local
`_patient`, `_stay` and `_record` builders (the totals and their content keys
are in `tests/unit/layout_ratchet_baseline.json`, the shared ratchet format of
`tests/unit/ratchet_baseline.py`). A new flat file or a new local builder fails
the test with the directory or fixture to use; moving a file to its mirrored
directory is not a new file; deleting one needs no baseline edit. The totals are
lowered by `python -m tests.unit.layout_ratchet --write` (a nightly job or the
maintainer, never inside a feature change).

## Run the tests of one module

The tests of one module live in several places: `tests/unit/<m>/`,
`tests/unit/modules/<m>/`, `tests/modules/<m>/`, flat `tests/unit/test_*<m>*.py`
files, `tests/simulator/` and `tests/integration/`. One command covers all of
them, so you do not need to know which exist:

```bash
python -m pytest tests/unit tests/modules tests/simulator tests/integration -k <m> -q -n 3
```

`<m>` is the module directory name under `clinosim/modules/` (for example
`drug_safety`). `-k` matches a test's file, directory, class and function names
as a case-insensitive substring, so a short name also selects other tests that
contain it (`hai` matches more than the `hai` module) and a test of the module
whose name never mentions it is not selected; combine keywords with
`-k "<m> or <related>"` where needed. Collecting the whole tree costs about
16 s before the first test runs. To skip that, list only the directories that
exist for the module (`ls -d tests/unit/<m> tests/unit/modules/<m> tests/modules/<m>`)
and pass them to `python -m pytest`.

Measured on a 14-core Mac with `-n 3` (the thread variables set to 1):

| Module | Directories that hold its tests | Command | Tests | Wall time |
| --- | --- | --- | --- | --- |
| `drug_safety` | `tests/unit/drug_safety/`, `tests/unit/modules/drug_safety/`, `tests/modules/drug_safety/`, flat files, `tests/integration/` | the command above, `-k drug_safety` | 328 | 20.9 s |
| `drug_safety` | the three directories only | `python -m pytest tests/unit/drug_safety tests/unit/modules/drug_safety tests/modules/drug_safety -q -n 3` | 242 | 3.6 s |
| `immunization` | `tests/unit/modules/immunization/`, flat files, `tests/integration/` | the command above, `-k immunization` | 343 | 23.7 s |
| `immunization` | the one directory only | `python -m pytest tests/unit/modules/immunization -q -n 3` | 248 | 4.8 s |

The directory-only forms are faster and skip the flat and integration tests, so
run the full command before you open a pull request. CI is unchanged: it runs
every directory.

## Marker policy — path is authoritative

Pytest markers today (~745× `unit`, ~221× `integration`) are decorative:
CI selects by directory (`tests/unit/**` → unit, etc.), not by marker.
Do not add per-module `pytestmark = pytest.mark.unit` boilerplate — the
directory encodes the same fact. Reserve markers for cross-cutting selectors
that a path cannot express.

## Marker vocabulary

Declared in `pyproject.toml [tool.pytest.ini_options] markers`:

| Marker        | Meaning                                                            |
| ------------- | ------------------------------------------------------------------ |
| `unit`        | fast, no filesystem beyond fixtures                                |
| `integration` | multi-module chain, may touch tmp filesystem                       |
| `e2e`         | full simulation run, slow                                          |
| `regression`  | AD-66 α-min narrative regression suite (opt-in)                    |
| `serial`      | mutates shared filesystem/global state — xdist runs it single-worker |

`slow` is NOT a marker. Sharding is duration-based via `.test_durations`, not
marker-based: PR CI splits the unit and integration suites into shards by whole
test file with `scripts/ci_split_by_file.py` (a file weighs the sum of its
tests' durations in `.test_durations`, and files are bin-packed longest first
onto the least-loaded shard). Do not add `pytest.mark.slow`.

Do not mix `unit` and `integration` markers in the same file — put integration
cases under `tests/integration/`.

## Fixture policy

- **Patient fixtures**: use the canonical `patient_factory` fixture
  (`tests/conftest.py`, added by Issue #567) for building `PatientProfile`
  instances in new tests. Use `load_patient_profile(profile_id)` for the six
  YAML profiles under `tests/fixtures/patient_profiles/` — loader still
  scoped to `tests/regression/` (unit-scope exposure pending Issue #567
  follow-up). Do NOT add a new local `_patient()`, `_stay()` or `_record()` helper (the
  layout guard above fails a new one); the existing duplicates will be migrated
  in follow-up PRs.
- **Bundle-context**: use the shared `BundleContext` builder from
  `tests/integration/_sr_helpers.py` for integration tests that need one.
- **Country/locale**: default is US (per `AGENTS.md § Country / locale
  convention`). JP-specific fixtures gate on `is_jp(country)` and require
  `CLINOSIM_JP_CLINS_PKG_DIR` env for cohort generation.

## Numeric tolerance

Prefer `pytest.approx(value, abs=…)` over `abs(x - y) < eps`. When multiple
tests enforce the same invariant (e.g. "distribution sums to 1"), use the
**same** tolerance across files. `1e-9` is the default absolute tolerance for
sum-to-one; do not relax without justification.

Follow-up (Issue #567 companion): `tests/_numerics.py` will expose
`assert_sums_to_one(seq, atol=1e-9)` and `assert_close(a, b, rel_tol=1e-9)` —
migrate to those once landed.

## Assertion messages

Add `assert x, "msg"` only when the failure line alone doesn't identify the
invariant. Obvious asserts (`assert result == expected`) stay bare — pytest
already prints a useful diff.

## `.test_durations` refresh

Duration file at repo root drives the shard split of PR CI
(`scripts/ci_split_by_file.py` sums it per test file). The nightly workflow
(`.github/workflows/nightly.yml`) measures it per shard in the `ci.yml` layout
and opens (or updates) a PR that refreshes it. That PR is opened with
`GITHUB_TOKEN`, so its `pull_request` runs (`ci.yml`, `dco.yml`) wait for
approval; the nightly job approves them (or, when the token may not approve,
dispatches both workflows on the branch after them) and sets auto-merge: the
refresh lands without a maintainer step when the checks pass.
A new test file without an entry weighs as the mean file until the next
nightly run, so a PR does not need to refresh the file itself.

## Related backlog

- **Layout sweep** (top-level → mirrored): Issue #567
- **`patient_factory` fixture**: added to `tests/conftest.py` (Issue #567)
- **`_patient()` helper migration** (existing 8 divergent copies → canonical fixture): Issue #567 follow-up
- **Unit-scope `load_patient_profile(profile_id)` exposure** (currently scoped to `tests/regression/`): Issue #567 follow-up
- **Numeric-tolerance helper module**: Issue #567 follow-up
- **Marker enforcement `conftest.py`** (auto-apply by path): Issue #567 follow-up

When any of the follow-ups lands, update the linked section above.
