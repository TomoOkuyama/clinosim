Addresses #N
<!-- First line, on its own: `Addresses #N` when this PR fully resolves the issue, or `Part of #N` when something the issue asks for is left out (say what remains below). One issue per line. Do not use GitHub closing keywords (Closes, Fixes, Resolves): they also fire on negated text. -->

## Summary

<!-- What was wrong or what is restructured, the cause, the change. One physical line per paragraph. If this is `Part of #N`, say what remains. -->

## Kind of change

<!-- Pick one. A refactoring and a behavior change are separate PRs. Domain experts: the label `refactoring` or `behavior-change` is added by a maintainer from this choice. -->

- [ ] Refactoring (no output change)
- [ ] Behavior change (output changes)
- [ ] Docs only
- [ ] CI / tooling only

## Refactoring evidence

<!-- Only for a refactoring; write "n/a" otherwise. -->

- [ ] US and JP cohorts (seed 42, population 200, `--start 2025-07-01 --end 2026-06-30`, CIF + FHIR) are byte-identical to the base commit. State the result per country:
- [ ] The regression goldens are unchanged
- [ ] The number and order of RNG draws are unchanged

## Behavior change evidence

<!-- Only for a behavior change; write "n/a" otherwise. -->

**CIF changes**: <!-- Describe the structured-CIF change (a MINOR-class change), or write "FHIR only". -->

Before and after numbers (metric, cohort, seed):

| Metric | Cohort and seed | Before | After |
|---|---|---|---|
| | | | |

Golden diff, explained per profile (which profiles moved and why):

## Sources

<!-- Every new or changed clinical number, code or dose needs a source you read: quote the value and say where in the source it is (label section, table, guideline page, PMID/DOI, tx.fhir.org lookup). Write "no clinical numbers, codes or doses" if none. If you copied terminology text, give its license. A change without a source gets the label `needs-source`. -->

## Checks run

- [ ] `pytest tests/unit tests/modules tests/simulator` passes (the set CI runs)
- [ ] Integration tests of every touched module pass
- [ ] `ruff check clinosim tests` and `ruff format --check clinosim tests` pass
- [ ] `mypy clinosim/` passes
- [ ] `vulture clinosim .vulture-whitelist.py --min-confidence 60` prints nothing
- [ ] `python -m tests.unit.code_data_separation` baseline did not go up
- [ ] Not run (list what and why):

## Documentation

- [ ] English and Japanese docs are updated as a pair (`*.md` and `*.ja.md`)
- [ ] Module README / SPEC updated when behavior or structure changed
- [ ] `CHANGELOG.md` `[Unreleased]` has a user-facing bullet (skip for docs-only)

## Checklist

- [ ] All commits are signed off (`git commit -s`); the DCO check fails otherwise
- [ ] No real patient data, PHI, or PII introduced
- [ ] No proprietary vendor code or trademarks introduced
- [ ] License header preserved (MIT)

## Notes for reviewers

<!-- Rationale for a non-obvious choice, alternatives rejected, known follow-up work. -->
