# Cross-platform determinism — bit-reproducible RNG variates (session 90)

**Date**: 2026-08-28
**PR**: [#906](https://github.com/TomoOkuyama/clinosim/pull/906)
**Branch**: `fix/deterministic-rng-cross-platform`
**Version**: bundled into `v0.5.0`

## Problem

Session s88j-late (2026-08-20) verified that regenerating the same
seed on Mac ARM (Apple Silicon) vs H100 x86 Linux produced **41,983
files vs 41,970 files** at `p=10000 s=500`, with content differences
in every "common" file. Root cause was traced to the per-patient
`delirium_susceptibility` field diverging at the last decimal digit:
`0.06889046377369229` (Mac) vs `0.06889046377369233` (H100).

That single-ULP drift shifted the downstream `numpy` PCG64 cursor, and
the shift cascaded through every subsequent sampling call, producing a
completely different cohort on each platform.

## Root cause

`numpy.random.Generator.beta` / `.normal` / `.exponential` all reach
platform ``libm`` for the transcendental steps of the sampling
algorithm:

- `beta(a, b)` uses Marsaglia-Tsang gamma variates → `log`, `pow`
- `normal(loc, scale)` uses Box-Muller (or Ziggurat with a rare
  `exp`/`log` fallback) → `log`, `cos`
- `exponential(scale)` uses inverse CDF → `log`

IEEE 754 mandates correct rounding for basic arithmetic + `sqrt`, but
NOT for transcendentals. Apple Accelerate/Neon and glibc `libm`
implementations differ at the last few ULP, and that drift enters the
`rng` state at the first `rng.beta()` / `.normal()` call.

## Fix

New `clinosim/determinism.py` module (256 LOC) reimplements the three
variates using only bit-identical primitives:

- **`rng.random()`** — pure integer arithmetic in numpy PCG64
  (`uint64 / 2^53`), guaranteed bit-identical across platforms
- **`mpmath.{log, exp, cos, pi}`** at 128-bit precision — pure Python
  integer arithmetic; the `float(mp.log(mp.mpf(x)))` round is IEEE 754
  mandated so bit-identical across platforms
- **`math.sqrt`** — IEEE 754 mandates correct rounding, bit-identical

Algorithms:

- Beta: Marsaglia-Tsang gamma → `x / (x + y)`
- Standard Normal: Box-Muller (`sqrt(-2 log u1) * cos(2π u2)`)
- Exponential: inverse CDF (`-scale * log(1 - u)`)

A tiny `_DeterministicRngProxy` (`__getattr__`-delegating wrapper)
overrides `beta` / `normal` / `exponential`, passes every other
Generator method (`random`, `integers`, `choice`, `permutation`, ...)
through unchanged. **10 sites** of `np.random.default_rng(seed)` were
changed to `determinism.default_rng(seed)` — no domain-code edits
touched the ~81 `rng.{beta,normal,exponential}` call sites in the
codebase.

Grand-design principle applied: **no new tunable constants in code.**
`mpmath.prec = 128` lives in `clinosim/config/determinism.yaml`.

## Verification

Fresh regeneration on Mac ARM (Apple Silicon, Python 3.12.7, numpy
2.5.1, mpmath 1.3.0) vs H100 x86 Ubuntu (Python 3.12.3, numpy 2.5.2,
mpmath 1.4.1):

| Cohort | Files | Diff |
|---|---|---|
| US p=100 s=42 | 24 | **0 (byte-identical)** ✅ |
| US p=500 s=42 | 25 | **0 (byte-identical)** ✅ |
| JP p=100 s=42 | 25 | 1 (Observation.ndjson only — JP-CLINS terminology package availability drift, not FP precision — separate issue) |

Primitive anchor at both platforms:

```
determinism.beta(seed=42, 2, 5) = 0.12974180459274487  hex: 3fc09b6123d32eac
```

Same hex on both Mac ARM and H100 x86 — the transcendentals are truly
bit-identical.

## Test coverage

- **4,791 unit tests pass** (+16 new determinism tests including a
  bit-pinned anchor value that will fire immediately if any future
  refactor breaks the algorithm).
- **316 integration tests pass** (1 fixture-seed migration:
  anticoag-carryforward `seed=43 → seed=45` — same class of drift as
  B-3's earlier migration; the determinism module changes RNG cadence
  so cohort composition differs at the same numeric seed).
- Within-Mac 2-run byte-identity verified (p=30 JP, p=50 US).

## Versioning

**MINOR** under the CIF↔narrative-CIF-consistency policy. Marsaglia-
Tsang / Box-Muller consume `rng.random()` at a different cadence than
numpy's Cheng-BB / Ziggurat, so structured CIF regenerates → narrative
CIF regenerates.

## Follow-ups (not blockers)

1. **JP p=100 Observation.ndjson difference** — track separately:
   `_UNCODED_SYSTEM` fallback fires on Mac when the JP-CLINS
   terminology package's dev-fallback path resolves differently
   (`~/workspace/fhir-jp-validator/tx-server-build/...`) between hosts.
   This is environment/config discovery, NOT floating-point precision,
   so it's out of scope for the determinism module.
2. **Downstream `math.exp` / `math.log10` in physiology labs** — these
   are called AFTER the RNG cursor is consumed, so their FP-precision
   drift only affects the emitted lab value, not downstream sampling.
   Currently deferred; would matter for cross-host byte-identity of
   the specific lab values themselves (not for cohort structure).

## Lessons learned

- **Transcendentals are the floor for cross-platform bit-identity.**
  IEEE 754 correct rounding stops at `sqrt`. Any code that calls
  `log`/`exp`/`pow`/`cos` through platform `libm` is a cross-platform
  determinism escape hatch.
- **The RNG proxy pattern generalizes.** `__getattr__` delegation +
  method-override for the three transcendental variates covers 81
  call sites without touching any of them. When future variates are
  needed (e.g. `gamma`, `dirichlet`), add them to the proxy and no
  domain code changes.
- **`mpmath` at 128-bit precision suffices** for bit-identical
  transcendentals bounded to float64 output. Higher precision (256,
  512, ...) would be wasted work; 53-bit float64 significand is the
  ceiling.
- **Bit-pinned anchor tests are the strongest guard.** The
  `test_beta_anchor_seed42_2_5` test pins the hex representation
  `3fc09b6123d32eac`. Any future edit that shifts the algorithm by
  one ULP fires the test immediately.
