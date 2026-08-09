# ruff dead-code baseline sweep — 2026-08-09

**Scope**: [`ruff`](https://docs.astral.sh/ruff/) rules F401 (unused import)
and F841 (unused local variable) across `clinosim/**/*.py` and `tests/**/*.py`.

**Baseline commit**: `628326b6e2b` (documentation + code-quality policy
extraction).

**Policy reference**:
[`docs/design-guides/documentation-and-code-quality-policy.md`](../design-guides/documentation-and-code-quality-policy.md)
§6 (dead-code hygiene).

## Summary

**0 findings.** The current tree is already clean for F401 and F841. No
cleanup PR was needed.

The tree stayed clean without an explicit enforcement gate because the
existing `pyproject.toml` `[tool.ruff.lint]` configuration already includes
the `F` rule family in `select`, and the informational `Quality
(informational)` CI job runs `ruff check clinosim/ tests/` on every PR.
Contributors saw those warnings during PR review, and drift was cleaned up
opportunistically.

From now on, the check is a **required (merge-blocking)** CI job:
`ruff dead-code (F401 / F841)`. It runs
`ruff check --select F401,F841 clinosim/ tests/`. Any PR that introduces
an F401 or F841 violation fails this job and cannot merge.

## Reproduce

Run these against `master` (or any branch) to reproduce the baseline:

```bash
pip install "ruff==0.16.0"     # match CI-pinned version

ruff check --select F401,F841 clinosim/ tests/
# Expected: "All checks passed!"

ruff check --select F401,F841 --statistics clinosim/ tests/
# Expected: no statistics rows.
```

## Per-module baseline

Zero findings across every module. Reported for completeness so future
regressions can be attributed to a specific area quickly.

| Module | F401 | F841 |
|---|---:|---:|
| `clinosim/simulator/` | 0 | 0 |
| `clinosim/modules/` (all sub-modules) | 0 | 0 |
| `clinosim/modules/output/fhir_r4/` (all sub-directories) | 0 | 0 |
| `clinosim/audit/` | 0 | 0 |
| `clinosim/benchmarks/` | 0 | 0 |
| `clinosim/eval/` | 0 | 0 |
| `clinosim/codes/` | 0 | 0 |
| `clinosim/locale/` | 0 | 0 |
| `clinosim/types/` | 0 | 0 |
| `clinosim/dataset/` | 0 | 0 |
| `clinosim/config/` | 0 | 0 |
| `tests/unit/` | 0 | 0 |
| `tests/integration/` | 0 | 0 |
| **Total** | **0** | **0** |

## Out-of-scope for this sweep

The following belong to related but separate Issues in the documentation
+ code-quality campaign:

- **Semantic dead code** (unused public API, unreachable via reflection)
  — Issue [#636](https://github.com/TomoOkuyama/clinosim/issues/636)
  (`vulture` scan).
- **Broader ruff Bugbear rules** (unreachable branches, jump-in-finally,
  etc.) — deferred; a follow-up Issue can adopt individual `B` rules
  after inspecting the current tree for pre-existing debt.
- **Unused-parameter checks** (Ruff `PLR6301` or the built-in
  `ARG` rule family) — deferred; protocol overrides and callback
  signatures generate high false-positive rates without a per-file
  ignore mechanism.

## Change history

- **2026-08-09** — Baseline established. New required CI job
  `ruff dead-code (F401 / F841)` added in the PR closing
  [Issue #635](https://github.com/TomoOkuyama/clinosim/issues/635).
