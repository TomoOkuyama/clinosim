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

The script runs `clinosim simulate --format fhir` twice per locale
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

## Cross-platform byte-identity (v0.5.0+)

The above invariants get you byte-identical output **within the same
CPU architecture** (two Mac ARM runs match; two x86 Linux runs match).
Cross-architecture identity requires an extra guarantee: the
transcendental functions used inside sampling algorithms must round
identically on every platform. `numpy.random.Generator.beta` /
`.normal` / `.exponential` reach the platform `libm` for
`log` / `exp` / `pow` / `cos`, and IEEE 754 mandates correct rounding
only for basic arithmetic + `sqrt` — not for transcendentals. Apple
Silicon and glibc `libm` differ at the last few ULP, and any single
drift shifts the numpy RNG cursor for every subsequent draw.

Since v0.5.0, clinosim ships `clinosim.determinism` — a bit-reproducible
drop-in for those three variates on top of two primitives that ARE
bit-identical everywhere:

- `rng.random()` (pure integer arithmetic in numpy PCG64)
- `mpmath.{log, exp, cos}` at 128-bit precision (pure Python integer
  arithmetic)

A tiny proxy wraps every `np.random.default_rng(seed)` at the simulator
entry points; downstream call sites keep the same `rng.beta(...)`
API. **No user action is required** — the module is on by default.

Verified against a fresh regen on Mac ARM (macOS 26, Python 3.12.7,
numpy 2.5.1, mpmath 1.3.0) vs an H100 x86 Ubuntu host (Python 3.12.3,
numpy 2.5.2, mpmath 1.4.1): US p=100 s=42 → 24/24 files identical, US
p=500 s=42 → 25/25 files identical. See
[`docs/reviews/2026-08-28-cross-platform-determinism.md`](../reviews/2026-08-28-cross-platform-determinism.md)
for the full story (problem statement, root cause, algorithm design,
verification, lessons).

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
