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
New tests go under the mirrored subdirectory. Do not add new files to
`tests/unit/` directly.

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
marker-based. Do not add `pytest.mark.slow`.

Do not mix `unit` and `integration` markers in the same file — put integration
cases under `tests/integration/`.

## Fixture policy

- **Patient fixtures**: use the canonical `patient_factory` fixture (planned
  in Issue #567) and `load_patient_profile(profile_id)` for the six YAML
  profiles under `tests/fixtures/patient_profiles/`. Do not add another local
  `_patient()` helper — 8 near-duplicates already exist.
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

Duration file at repo root drives xdist sharding. Refresh policy:

- Regenerate on any change that adds/removes ≥5 tests or shifts a slow test's
  runtime by ≥2×.
- Run `pytest --store-durations` locally against the full suite (unit +
  integration) and commit the diff in the same PR that changed test count.

## Related backlog

- **Layout sweep** (top-level → mirrored): Issue #567
- **Canonical `patient_factory` fixture**: Issue #567
- **`_patient()` helper consolidation** (8 divergent copies): Issue #567
- **Numeric-tolerance helper module**: Issue #567 follow-up
- **Marker enforcement `conftest.py`** (auto-apply by path): Issue #567 follow-up

When any of the follow-ups lands, update the linked section above.
