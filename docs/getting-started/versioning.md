# Versioning & releases

clinosim follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html):

- **MAJOR** — incompatible API / CIF / FHIR schema changes.
- **MINOR** — backward-compatible feature additions (new modules, new
  resource types, additional locale support). May change output
  byte-for-byte even at the same seed.
- **PATCH** — backward-compatible bug fixes and data-quality corrections
  that preserve the CIF/FHIR schema. **Byte-identical output within the
  same seed is a hard guarantee for PATCH releases within one MINOR
  line.**

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
```

Release notes are extracted automatically from `CHANGELOG.md`.

## Changelog

Full history: [Changelog](../development/changelog.md).
