# Release checklist

Every item below is required before a release tag (`vX.Y.Z`) is pushed. The tag push is irreversible: PyPI does not accept a re-upload of a version (see [Publishing to PyPI](publishing-to-pypi.md)), so a problem found after the tag costs a new patch release. Work through the sections in order on the commit that will be tagged, and record the results (numbers, run links) in the release PR or the release notes.

Bumping `__version__`, replacing the CHANGELOG heading and pushing the tag happen only after every section below is complete and the maintainer has approved the release.

## 1. Documentation matches the code

- [ ] `CHANGELOG.md` `## [Unreleased]` lists every PR merged since the previous tag. Compare `git log vPREV..HEAD --oneline` with the entries; every change that alters CIF values is marked as such.
- [ ] The version class follows the versioning policy: a change that alters CIF (or CIF and its narrative) is MINOR; a FHIR-only change is PATCH.
- [ ] Module `README.md` / `SPEC.md` files of every module changed since the previous tag describe the current behavior: formulas, constants, defaults and file names quoted in them match the code.
- [ ] Every English page changed since the previous tag has its `.ja.md` counterpart updated, and the reverse (`git diff --stat vPREV..HEAD -- '*.md'`).
- [ ] Counts and defaults stated in `README.md` and `docs/` (diseases, resource types, CLI defaults) match the code.
- [ ] `mkdocs build --strict` passes locally (the `docs.yml` workflow runs the same command).

## 2. Generation speed has not regressed

- [ ] Generate the same cohort with the previous tag and with the release commit (same country, `--population`, `--seed`; one US and one JP run) and record wall-clock time and peak memory for CIF and FHIR generation.
- [ ] Record template narrative (`clinosim narrate`) throughput the same way.
- [ ] A slowdown above 20 % on either step is investigated before the release; it is either fixed or explained in the release notes.
- [ ] Add the measured numbers to the release PR so the next release has a baseline.

## 3. Quality gates are green on the release commit

- [ ] `Nightly` run manually (`workflow_dispatch`) on the release commit, all jobs green (reproducibility and the slow e2e tests).
- [ ] `US Core narrow compliance gate` and `JP compliance gate (JP-CLINS lab + JP Core)` green on the release commit.
- [ ] `US FHIR validate` and `JP FHIR validate` green (run manually if they did not run on the release commit).
- [ ] A fresh US and JP cohort from the release commit scored with `clinosim eval` ([eval](../eval.md)); no axis is lower than at the previous tag without an explanation.
- [ ] Whole-cohort data-quality review of the fresh cohorts (structural, temporal, causal, longitudinal, locale, terminology, narrative, document density) and a per-patient review of a stratified sample; every confirmed problem is filed as an issue and triaged as release blocker or not.
- [ ] `python scripts/verify_medical_stats.py <cohort_dir> <US|JP>` on both cohorts; prevalence, LOS, mortality and event rates stay within their target bands, and every metric that moved is explained by a CHANGELOG entry.

## 4. Changes against the previous release are explained

- [ ] Compare the aggregate figures (resource counts per type, LOS, mortality, document counts) of the cohorts generated in section 2 for the previous tag and the release commit; each notable difference maps to a CHANGELOG entry.
- [ ] Generated cohorts are deleted after the figures are recorded.

## 5. The package installs and runs

- [ ] Build the wheel (`python -m build`, `twine check dist/*`), install it in a clean virtual environment and run a small `clinosim simulate` for US and JP; no missing data file or import error.
- [ ] The dataset presets that `release.yml` builds (us-100 / us-1000 / jp-100 / jp-1000) build locally with the same environment the workflow uses.

## 6. Issues and pull requests are settled

- [ ] No open pull request that is meant for this release.
- [ ] Open `bug` and `data-quality` issues triaged; none is a release blocker, or the blocker is fixed.
- [ ] Every issue fixed by a merged PR is closed (a PR body without `Addresses #N` does not close its issue).

## 7. Cut the release

Only after the maintainer's approval, follow [Publishing to PyPI](publishing-to-pypi.md) "Cutting a release": bump `__version__`, move the `## [Unreleased]` content under the new version heading, commit, push the tag, and watch `release.yml` until the GitHub Release and the PyPI upload are complete.
