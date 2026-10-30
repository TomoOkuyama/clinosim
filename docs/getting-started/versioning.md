# Versioning & releases

clinosim's SemVer scoping anchors on **CIF ↔ narrative-CIF consistency**,
not the generic SemVer spec's module boundary. The canonical rules live
in [`CHANGELOG.md`](../development/changelog.md) ("Versioning policy
(from v0.4.0 onward)" at the top of that file); in short:

- **MAJOR** — Python-API breaks (import paths, public function
  signatures, CLI option removals that break scripted users).
- **MINOR** — a change that breaks CIF ↔ narrative-CIF consistency
  (CIF schema change, narrative-CIF drift, new resource type that
  carries structural fields through CIF). May change output byte-
  for-byte even at the same seed.
- **PATCH** — a change that preserves CIF ↔ narrative-CIF consistency,
  including FHIR-emit-only fixes, locale display corrections, and
  data-quality corrections that touch neither CIF nor narrative-CIF
  structural fields.

See `CHANGELOG.md` for the full policy and the per-release reasoning.

## Cutting a release

Version lives in exactly one place: `clinosim/__init__.py::__version__`.
`pyproject.toml` reads it dynamically (`[tool.hatch.version]`), so PyPI
metadata, `pip show clinosim`, and `import clinosim; print(clinosim.__version__)`
never drift.

```bash
# 1. Bump the version and update the changelog
$EDITOR clinosim/__init__.py       # e.g. __version__ = "0.3.0"
$EDITOR CHANGELOG.md               # move [Unreleased] entries under [0.3.0] - YYYY-MM-DD

# 2. Commit and tag
git add clinosim/__init__.py CHANGELOG.md
git commit -m "release: v0.3.0"
git tag -a v0.3.0 -m "clinosim v0.3.0"
git push origin master --tags

# 3. The release workflow fires automatically:
#    - builds sdist + wheel
#    - twine-checks metadata
#    - builds the 4 dataset presets (us-100, us-1000, jp-100, jp-1000)
#    - creates a GitHub Release with wheel + sdist + dataset tarballs
#    - publishes wheel + sdist to PyPI (Trusted Publishing / OIDC)
```

Release notes are extracted automatically from `CHANGELOG.md`.

## Changelog

Full history: [Changelog](../development/changelog.md).
