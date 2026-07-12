<!--
Thanks for the contribution! Fill in the sections below. You can delete this
comment block before submitting.

If your PR is a work in progress, open it as a draft.
-->

## Summary

<!-- One or two sentences on what this PR does and why. -->

## Related issue

<!-- Fixes #123, refs #456. Non-trivial PRs should be tied to an existing issue. -->

## Type of change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change (would require a MAJOR version bump)
- [ ] Docs / infrastructure only

## Determinism impact

<!-- Any change that touches simulation paths must state its determinism impact.
     If in doubt, run the same seed twice and compare byte output. -->

- [ ] No impact — pure docs / packaging / CI
- [ ] Additive, new code path — output at existing seeds is byte-identical
- [ ] Changes existing output — this PR needs a MINOR version bump and a CHANGELOG entry describing what changed
- [ ] Verified byte-identical at seed 42 with a JP p=1000 cohort (`clinosim generate --country JP --population 1000 --seed 42 --start 2026-01-01 --end 2026-06-30`)

## Checklist

- [ ] All commits are signed off (`git commit -s`) — DCO check will fail otherwise
- [ ] `pytest tests/unit -q` passes locally
- [ ] `pytest tests/integration -q` passes locally (required when touching simulator / output / FHIR paths)
- [ ] `CHANGELOG.md` `[Unreleased]` section updated with a user-facing bullet
- [ ] Documentation updated when a new module / YAML field / CLI subcommand / public API is added
- [ ] No real patient data, PHI, or PII introduced
- [ ] No InterSystems-specific code / trademarks introduced
- [ ] License header preserved (MIT)

## Notes for reviewers

<!-- Anything you want called out: rationale for a non-obvious choice, alternatives you considered and rejected, known follow-up work, etc. -->
