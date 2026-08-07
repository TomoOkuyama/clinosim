# Publishing clinosim to PyPI

The release workflow (`.github/workflows/release.yml`) builds a wheel + sdist
and creates a GitHub Release on every `v*.*.*` tag push, but the actual PyPI
upload step is intentionally commented out until a maintainer configures a
publishing credential.

Two supported paths — pick one and edit `release.yml` per the inline comments.

## Path A — PyPI Trusted Publisher (recommended, no secret)

PyPI trusted publishing uses GitHub OIDC to authenticate the workflow directly
against PyPI, so no long-lived token needs to be stored as a repository secret.
This is the modern PyPI-recommended path.

### One-time setup (maintainer)

1. Register the package name on PyPI: <https://pypi.org/manage/projects/> →
   "Register a new project" → name `clinosim`. First-time only.
2. On <https://pypi.org/manage/account/publishing/> add a "Pending Trusted
   Publisher" with:
   - PyPI Project name: `clinosim`
   - Owner: `TomoOkuyama`
   - Repository name: `clinosim`
   - Workflow name: `release.yml`
   - Environment name: leave blank (or set `pypi` if you want a
     required-approval step)
3. Edit `.github/workflows/release.yml`:
   - Under `permissions:` uncomment `id-token: write`
   - Uncomment the `- name: Publish to PyPI (trusted publishing)` step at the
     bottom of the job

### Verify

- Cut a pre-release tag (e.g., `v0.2.0rc1`), push, watch the release job
- On success, `pip install clinosim==0.2.0rc1` should work

## Path B — API token (simpler, uses a secret)

If trusted publishing is unavailable in the target org, fall back to an API
token stored as a repository secret.

### One-time setup

1. Register the project on PyPI (same as A step 1)
2. Create an API token scoped to just the `clinosim` project at
   <https://pypi.org/manage/account/token/>
3. Add it to the repo as `PYPI_API_TOKEN` under Settings → Secrets and
   variables → Actions
4. Edit `.github/workflows/release.yml`: uncomment the `- name: Publish to
   PyPI (token)` step

## Cutting a release (both paths)

1. Bump `clinosim/__init__.py::__version__` (e.g. `0.2.0 → 0.3.0`)
2. Move `## [Unreleased]` content in `CHANGELOG.md` under a new
   `## [X.Y.Z] - YYYY-MM-DD` heading
3. `git commit -am "release: vX.Y.Z"` + push to master
4. `git tag -a vX.Y.Z -m "clinosim vX.Y.Z"` + `git push origin vX.Y.Z`
5. `release.yml` fires on the tag push and:
   - Verifies `tag == clinosim.__version__` (refuses mismatch)
   - Builds sdist + wheel + dataset presets (us-100 / us-1000 / jp-100 / jp-1000)
   - Publishes GitHub Release with artifacts + CHANGELOG entry as notes
   - (After enabling A or B above) Publishes to PyPI

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
