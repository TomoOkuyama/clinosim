# Publishing clinosim to PyPI

The release workflow (`.github/workflows/release.yml`) fires on every
`v*.*.*` tag push. It builds a wheel + sdist, creates a GitHub Release, and
uploads the wheel + sdist to PyPI in the same job.

## PyPI Trusted Publishing (OIDC)

The PyPI upload uses Trusted Publishing: GitHub OIDC authenticates the
workflow directly against PyPI, so no long-lived token is stored in the
repository. The trusted publisher is registered at
<https://pypi.org/manage/project/clinosim/settings/publishing/> with:

- PyPI Project name: `clinosim`
- Owner: `TomoOkuyama`
- Repository name: `clinosim`
- Workflow name: `release.yml`
- Environment name: `release`

In `release.yml` the `release` job runs in the `release` environment and
holds `id-token: write`; the `Publish to PyPI (Trusted Publishing / OIDC)`
step (`pypa/gh-action-pypi-publish@release/v1`, `packages-dir: dist/`)
performs the upload. If the job's environment name and the one registered
on PyPI differ, PyPI rejects the token exchange.

## Cutting a release

1. Bump `clinosim/__init__.py::__version__` (e.g. `0.2.0 → 0.3.0`)
2. Move `## [Unreleased]` content in `CHANGELOG.md` under a new
   `## [X.Y.Z] - YYYY-MM-DD` heading
3. `git commit -am "release: vX.Y.Z"` + push to master
4. `git tag -a vX.Y.Z -m "clinosim vX.Y.Z"` + `git push origin vX.Y.Z`
5. `release.yml` fires on the tag push and:
   - Verifies `tag == clinosim.__version__` (refuses mismatch)
   - Builds sdist + wheel and runs `twine check`
   - Builds the dataset presets (us-100 / us-1000 / jp-100 / jp-1000) with
     `CLINOSIM_ALLOW_LEGACY_JP_CLINS_PKG=1` (the runner has no JP-CLINS
     package, so the JP presets carry legacy 5-digit JLAC10 OIDs)
   - Publishes the GitHub Release with the sdist, wheel and dataset tarballs
     attached and the CHANGELOG entry as notes
   - Publishes the sdist + wheel to PyPI (dataset tarballs go to the GitHub
     Release only)
   - Uploads `dist/*` as a workflow artifact (90-day retention)

## Roll-forward-only

PyPI does not allow re-publishing a version. If a release goes out with a
bug, bump the patch version and re-cut. Never delete + re-upload the same
version number.

## Related workflows

- `nightly.yml` — reproducibility gate on master. Run manually before a
  release cut (`workflow_dispatch`) to catch any silent determinism drift
  since the last nightly.
- `jp-clins-lab-compliance-gate.yml` — JP-CLINS invariant check. Must be
  green on the release commit before the tag push.
