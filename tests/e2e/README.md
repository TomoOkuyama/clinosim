# `tests/e2e/` — End-to-end simulation integration suite

Opt-in pytest tier (`pytest -m e2e`) that runs the full simulation pipeline on representative cohorts and checks the aggregate output. Covers the beta mode (`run_beta`), alpha-golden snapshot, forced-scenario path, and both US / JP locale smoke runs.

## Scope — what belongs here

- **Full-cohort simulation**: tests that call `clinosim generate ...` or `simulator.engine.run_beta(...)` with a small-but-complete cohort (typically p=10-100).
- **Cross-cohort invariants**: aggregate distributions, cohort fingerprints, cross-locale symmetry.
- **CLI contract**: argparse behavior, exit codes, output-format shape (NDJSON header, FHIR bundle shape).
- **Beta vs alpha mode equivalence**: cross-engine invariants.

## Not in scope — belongs in `tests/regression/`

- AD-66 patient-profile golden snapshots (per-profile narrative + structure byte-fidelity).
- Tests anchored on a single `tests/fixtures/patient_profiles/*.yaml` fixture.

The two directories are intentionally separate because the pytest markers (`e2e` vs `regression`) correspond to different CI pipelines; see [`../regression/README.md`](../regression/README.md) for the full comparison table.

## Adding tests here

1. Confirm the new test touches the full simulation pipeline (not just a per-profile golden check).
2. Add `@pytest.mark.e2e` to the test function.
3. Keep cohort size modest (p ≤ 100 typically) — e2e tier is already the slowest tier in CI.
4. If the new test asserts byte-level fidelity against a committed golden, add a corresponding fixture-regeneration CLI incantation to the test docstring so a future contributor can refresh it after an intentional template change.
