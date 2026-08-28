"""Bit-reproducible random variates for cross-platform byte-identity.

The problem
-----------

``numpy.random.Generator.beta``, ``.normal``, ``.exponential`` all go
through the platform ``libm`` for ``log`` / ``exp`` / ``pow`` / ``sin`` /
``cos``. These functions are NOT guaranteed to be bit-identical across
CPU architectures — IEEE 754 mandates correct rounding only for basic
arithmetic and ``sqrt``, not for transcendentals. Apple Silicon
Accelerate/Neon differs from x86 glibc at the last few ULP, and that
single-bit drift cascades through the numpy RNG state so the entire
downstream CIF diverges (verified session s88j-late: Mac 41,983 files
vs H100 41,970 files at ``p=10000 s=500``, plus content differences
in every "common" file).

The remedy
----------

This module reimplements Beta / standard-Normal / Exponential variates
using only:

1. ``rng.random()`` — pure integer arithmetic in numpy PCG64, guaranteed
   bit-identical across platforms.
2. ``math.sqrt`` — IEEE 754 mandates correct rounding, bit-identical.
3. ``mpmath.{log, exp, cos, pi}`` at fixed precision — pure Python
   integer arithmetic under the hood; the ``float(mp.log(mp.mpf(x)))``
   round is IEEE 754 mandated, so bit-identical.

Every call consumes only ``rng.random()`` for its source of randomness.
The distribution shape (Marsaglia-Tsang for Gamma, Box-Muller for
Normal, inverse CDF for Exponential) is preserved by the algorithm.

Precision budget
----------------

``mpmath.prec = 128`` (128 bits ≈ 38 decimal digits) provides > 2x the
53-bit float64 significand, so the final ``float()`` round is well
within 0.5 ULP for every reasonable input. Higher precision would be
wasted work; lower risks last-bit drift.

Usage
-----

>>> import numpy as np
>>> from clinosim.determinism import beta, normal, exponential
>>> rng = np.random.default_rng(42)
>>> beta(rng, 2.0, 5.0)       # doctest: +SKIP
0.12974180459274487
>>> normal(rng, mean=0.0, sd=1.0)      # doctest: +SKIP
>>> exponential(rng, mean=1.0)         # doctest: +SKIP

Design constraint
-----------------

**No new tunable constants live in this file.** The ``PRECISION_BITS``
constant sits in ``clinosim/config/determinism.yaml`` (loaded once at
import) per the grand-design principle that tunable numbers live in
external config, not code.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from mpmath import cos as _mp_cos
from mpmath import log as _mp_log
from mpmath import mp, mpf
from mpmath import pi as _mp_pi
from mpmath import power as _mp_power

if TYPE_CHECKING:
    import numpy as np


_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "determinism.yaml"


def _load_precision_bits() -> int:
    """Load ``mpmath.prec`` from yaml. Fail loud on any parse issue —
    this is a determinism-critical setting, silent fallback would defeat
    the purpose."""
    with open(_CONFIG_PATH) as fh:
        cfg = yaml.safe_load(fh)
    return int(cfg["mpmath_precision_bits"])


mp.prec = _load_precision_bits()
_TWO_PI_FLOAT: float = float(2 * _mp_pi)


# ---------------------------------------------------------------------------
# Bit-reproducible transcendental primitives
# ---------------------------------------------------------------------------


def _log(x: float) -> float:
    """``log(x)`` rounded to nearest float64 via mpmath (bit-identical
    across platforms). ``x`` must be positive."""
    return float(_mp_log(mpf(x)))


def _cos(x: float) -> float:
    """``cos(x)`` rounded to nearest float64 via mpmath (bit-identical)."""
    return float(_mp_cos(mpf(x)))


def _pow(x: float, y: float) -> float:
    """``x ** y`` rounded to nearest float64 via mpmath (bit-identical).
    Integer exponents defer to Python's ``**`` (bit-identical already)."""
    if y == int(y):
        return x ** int(y)
    return float(_mp_power(mpf(x), mpf(y)))


# ---------------------------------------------------------------------------
# Standard variates on top of rng.random()
# ---------------------------------------------------------------------------


def _standard_normal(rng: np.random.Generator) -> float:
    """Box-Muller standard normal variate. Consumes 2 ``rng.random()``
    calls per variate (the second Box-Muller output is discarded — we
    prioritize algorithmic simplicity over one-call efficiency).

    Rejection: if ``u1 == 0`` (probability 2^-53), we substitute a tiny
    positive value so ``log`` does not diverge. This preserves the
    RNG-shape invariant (still 2 draws per call)."""
    u1 = float(rng.random())
    u2 = float(rng.random())
    if u1 <= 0.0:
        u1 = 1e-300
    return math.sqrt(-2.0 * _log(u1)) * _cos(_TWO_PI_FLOAT * u2)


def _standard_gamma(rng: np.random.Generator, shape: float) -> float:
    """Marsaglia-Tsang standard gamma variate for ``shape > 0``. Consumes
    a variable number of ``rng.random()`` calls (rejection loop; each
    iteration takes 3-4 draws). Determinism is preserved because the
    accepted iteration is a pure function of the draws.

    Boost for ``shape < 1`` uses the well-known ``G(k) = G(k+1) *
    U^(1/k)`` identity."""
    if shape <= 0.0:
        raise ValueError(f"shape must be positive, got {shape!r}")
    if shape < 1.0:
        # Boost trick — one extra U draw
        u = float(rng.random())
        return _standard_gamma(rng, shape + 1.0) * _pow(u, 1.0 / shape)
    d = shape - 1.0 / 3.0
    c = 1.0 / math.sqrt(9.0 * d)
    while True:
        x = _standard_normal(rng)
        v = 1.0 + c * x
        if v <= 0.0:
            continue
        v = v * v * v  # integer exponent — bit-identical
        u = float(rng.random())
        # Marsaglia-Tsang squeeze then log test
        if u < 1.0 - 0.0331 * (x * x) * (x * x):
            return d * v
        if _log(u) < 0.5 * x * x + d * (1.0 - v + _log(v)):
            return d * v


# ---------------------------------------------------------------------------
# Public API — matches numpy.random.Generator method signatures
# ---------------------------------------------------------------------------


def beta(rng: np.random.Generator, a: float, b: float) -> float:
    """Bit-reproducible ``Beta(a, b)`` variate. Drop-in replacement for
    ``rng.beta(a, b)`` when cross-platform byte-identity matters."""
    x = _standard_gamma(rng, a)
    y = _standard_gamma(rng, b)
    return x / (x + y)


def normal(rng: np.random.Generator, mean: float = 0.0, sd: float = 1.0) -> float:
    """Bit-reproducible ``Normal(mean, sd)`` variate. Drop-in replacement
    for ``rng.normal(mean, sd)`` when cross-platform byte-identity
    matters."""
    return mean + sd * _standard_normal(rng)


def exponential(rng: np.random.Generator, mean: float = 1.0) -> float:
    """Bit-reproducible ``Exponential(mean)`` variate via inverse CDF.
    Drop-in replacement for ``rng.exponential(mean)`` when cross-platform
    byte-identity matters."""
    u = float(rng.random())
    if u >= 1.0:
        u = 1.0 - 1e-300
    return -mean * _log(1.0 - u)


# ---------------------------------------------------------------------------
# RNG proxy — one wrap covers every downstream call
# ---------------------------------------------------------------------------


class _DeterministicRngProxy:
    """Transparent wrapper around ``numpy.random.Generator``. Every method
    other than ``beta`` / ``normal`` / ``exponential`` delegates to the
    underlying generator. Those three route through the bit-reproducible
    variate functions in this module.

    Two design choices:

    * ``__getattr__`` delegation covers the long tail (``choice``,
      ``integers``, ``random``, ``permutation``, ``bytes``, ...) without
      enumerating them.
    * The overridden methods keep the same *signature* as
      ``numpy.random.Generator`` (``rng.normal(loc, scale)`` etc.) so
      callers don't need to change. Scalar-only — if a call site ever
      needs ``size=``, add a real ``np.random.Generator`` fallback in
      the override.
    """

    __slots__ = ("_rng",)

    def __init__(self, rng: np.random.Generator) -> None:
        self._rng = rng

    def beta(self, a: float, b: float) -> float:
        return beta(self._rng, a, b)

    def normal(self, loc: float = 0.0, scale: float = 1.0) -> float:
        return normal(self._rng, loc, scale)

    def exponential(self, scale: float = 1.0) -> float:
        return exponential(self._rng, scale)

    def __getattr__(self, name: str):
        return getattr(self._rng, name)

    def __repr__(self) -> str:
        return f"_DeterministicRngProxy({self._rng!r})"


def default_rng(seed: int | None = None) -> _DeterministicRngProxy:
    """Bit-reproducible drop-in for ``numpy.random.default_rng(seed)``.
    The returned object quacks like a ``numpy.random.Generator`` but its
    ``beta`` / ``normal`` / ``exponential`` methods produce byte-identical
    output across CPU architectures (Mac ARM vs x86 Linux)."""
    import numpy as np

    return _DeterministicRngProxy(np.random.default_rng(seed))
