<!-- Extracted from `README.md` (Issue #568 PR A2). Update the pointer in README when this file's heading changes. -->

# Testing

```bash
source .venv/bin/activate

# All tests (unit ~1 min, integration ~30 min, e2e ~8 min)
pytest -x

# By category
pytest -m unit                   # Unit tests (~2400 fast tests)
pytest -m integration            # Cross-module (includes reproduce.sh gate)
pytest -m e2e                    # E2E + golden tests

# Coverage
pytest --cov=clinosim
```

### Reproducibility

clinosim guarantees **byte-identical output** for a given
`(seed, config, country, start, end, population)` tuple within a MINOR
release line — wall-clock metadata (`fhir_r4/manifest.json`,
`cif/metadata.json`, narrative-pass `manifest.json`) is expected to
differ, everything else must match.

Verify at any time:

```bash
bash scripts/reproduce.sh
```

The script runs `clinosim simulate --format fhir` twice per locale
(US + JP by default) to two isolated temp directories, sha256s every
NDJSON + CIF JSON, and diffs the hash lists. Exit 0 = byte-identical,
exit 1 = determinism regression with the offending file(s) listed in
the diff. Environment variables `CLINOSIM_REPRO_COUNTRIES`,
`CLINOSIM_REPRO_POPULATION`, `CLINOSIM_REPRO_SEED`,
`CLINOSIM_REPRO_START`, `CLINOSIM_REPRO_END` override the defaults.

The CI `reproducibility` job runs this on every push and PR, so any
regression trips the merge gate before code lands.

---
