# `tests/regression/` — AD-66 patient-profile golden regression suite

Opt-in pytest tier that verifies byte-level fidelity of per-profile golden snapshots. Runs on demand (`pytest -m regression`) and in the nightly CI job; **not** part of the default `pytest -x` sweep because the suite reads full generated cohorts into memory per profile.

## Scope — what belongs here

- **Golden-file integrity**: every patient profile fixture under `tests/fixtures/patient_profiles/*.yaml` has a `<profile_id>.golden.json` snapshot. The tests confirm `clinosim.cli regenerate-goldens --profile <id>` output is byte-identical to the committed golden.
- **Narrative regression**: `test_narrative_profiles.py` runs the narrative generator on the fixtures and diffs against the committed narrative snapshot (AD-66 α-min-2c scope).

## Not in scope — belongs in `tests/e2e/`

- Full-cohort simulation runs (`clinosim generate --country US --population 100 ...` style).
- Cross-cohort invariants (R-/P-value distributions, aggregate medication-mix checks).
- CLI contract tests (argparse behavior, exit codes).

The two directories are intentionally separate because the pytest markers (`regression` vs `e2e`) correspond to different CI pipelines:

| Marker | Default sweep? | CI job | Scope |
|---|---|---|---|
| `regression` | opt-in only | nightly | AD-66 patient-profile golden fidelity |
| `e2e` | opt-in only | nightly + merge gate on tagged releases | Full-cohort simulation integration |

See `AGENTS.md` → "Testing conventions" for the full marker inventory. See [`.github/workflows/nightly.yml`](../../.github/workflows/nightly.yml) for which jobs run which markers.

## Adding tests here

1. Confirm the new test anchors on an AD-66 patient profile (not a broader cohort).
2. Add `@pytest.mark.regression` to the test function.
3. Make sure `pytest -m regression -k <new_test> -q` runs cleanly after `regenerate-goldens` is up to date.

If the new test is cohort-wide, place it under `tests/e2e/` instead.
