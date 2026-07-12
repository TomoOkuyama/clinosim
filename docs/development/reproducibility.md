# Reproducibility

clinosim guarantees **byte-identical output** for a given
`(seed, config, country, start, end, population)` tuple within a MINOR
release line — wall-clock metadata (`fhir_r4/manifest.json`,
`cif/metadata.json`, narrative-pass `manifest.json`) is expected to
differ, everything else must match.

## Verify at any time

```bash
bash scripts/reproduce.sh
```

The script runs `clinosim generate --format fhir` twice per locale
(US + JP by default) to two isolated temp directories, sha256s every
NDJSON + CIF JSON, and diffs the hash lists. Exit 0 = byte-identical,
exit 1 = determinism regression with the offending file(s) listed.

## Environment overrides

| Variable | Default |
|---|---|
| `CLINOSIM_REPRO_COUNTRIES` | `US JP` |
| `CLINOSIM_REPRO_POPULATION` | `50` |
| `CLINOSIM_REPRO_SEED` | `42` |
| `CLINOSIM_REPRO_START` | `2026-01-01` |
| `CLINOSIM_REPRO_END` | `2026-03-31` |
| `CLINOSIM_REPRO_KEEP_OUTPUT` | (unset) — set to keep temp dirs on success |

## CI enforcement

The `reproducibility` job in
[`.github/workflows/ci.yml`](https://github.com/TomoOkuyama/clinosim/blob/master/.github/workflows/ci.yml)
runs `scripts/reproduce.sh` on every push and PR. Any determinism
regression trips the merge gate before code lands.

## Underlying invariants

Per [AD-16](../reference/design.md):

- Every module derives a sub-seed from a master seed; no
  `random.random()` or global RNG state.
- Per-order lab RNG isolation (AD-59): specimen rejection / hemolysis /
  technician / noise are per-order sub-RNGs, so a YAML edit for one
  panel cannot shift unrelated patients' cohorts.
- Any commit that touches a seeded code path must be verified via
  `bash scripts/reproduce.sh` before it merges.

## When determinism breaks

If `scripts/reproduce.sh` reports a regression:

1. Read the diff — it names the offending file(s) with `+/-` sha256 lines.
2. Diff the two temp outputs directly to see the actual content
   difference (`export CLINOSIM_REPRO_KEEP_OUTPUT=1` and re-run).
3. The most common cause is Python's builtin `hash()` on a string
   (salted by `PYTHONHASHSEED`) — replace with
   `hashlib.sha256(...).hexdigest()`. Session 46 P1-7 uncovered exactly
   this defect in the immunization module's synthetic lot-number
   generator.

More context: [feedback / determinism story](https://github.com/TomoOkuyama/clinosim/blob/master/CHANGELOG.md).
