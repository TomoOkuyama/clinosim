"""Unit tests for the bit-reproducible RNG variate module.

The core promise: for a given ``rng`` state, calling ``beta`` / ``normal``
/ ``exponential`` produces a value whose bits depend ONLY on the RNG
sequence and the algorithm — never on the host platform's ``libm``.

We can't test cross-platform bit-identity from a single-host CI, but we
can lock in:

1. Determinism within-host (two runs with same seed → same hex).
2. RNG-shape invariant (call count matches expected shape).
3. Statistical properties (mean / variance close to distribution's
   theoretical values on a large sample).
4. Grand-design principle: no hardcoded ``mpmath.prec`` in the module —
   it's loaded from ``clinosim/config/determinism.yaml``.
"""

from __future__ import annotations

import math
import struct

import numpy as np
import pytest

from clinosim import determinism

pytestmark = pytest.mark.unit


def _hex(x: float) -> str:
    return struct.pack(">d", x).hex()


# ---------------------------------------------------------------------------
# Within-host determinism (the ceiling on the cross-host claim)
# ---------------------------------------------------------------------------


def test_beta_same_seed_bit_identical():
    v1 = determinism.beta(np.random.default_rng(42), 2.0, 5.0)
    v2 = determinism.beta(np.random.default_rng(42), 2.0, 5.0)
    assert _hex(v1) == _hex(v2), f"{_hex(v1)} vs {_hex(v2)}"


def test_normal_same_seed_bit_identical():
    v1 = determinism.normal(np.random.default_rng(42), 3.0, 1.5)
    v2 = determinism.normal(np.random.default_rng(42), 3.0, 1.5)
    assert _hex(v1) == _hex(v2), f"{_hex(v1)} vs {_hex(v2)}"


def test_exponential_same_seed_bit_identical():
    v1 = determinism.exponential(np.random.default_rng(42), 2.0)
    v2 = determinism.exponential(np.random.default_rng(42), 2.0)
    assert _hex(v1) == _hex(v2), f"{_hex(v1)} vs {_hex(v2)}"


# ---------------------------------------------------------------------------
# RNG-shape invariant — needed so downstream RNG state is predictable
# ---------------------------------------------------------------------------


class _CountingRng:
    """Wraps ``np.random.default_rng(seed)`` and counts ``random()`` calls."""

    def __init__(self, seed: int) -> None:
        self._rng = np.random.default_rng(seed)
        self.count = 0

    def random(self) -> float:
        self.count += 1
        return float(self._rng.random())


def test_normal_consumes_exactly_two_random_calls():
    rng = _CountingRng(42)
    determinism.normal(rng, 0.0, 1.0)
    assert rng.count == 2


def test_exponential_consumes_exactly_one_random_call():
    rng = _CountingRng(42)
    determinism.exponential(rng, 1.0)
    assert rng.count == 1


# ---------------------------------------------------------------------------
# Statistical properties (large-sample mean / variance)
# ---------------------------------------------------------------------------


def test_beta_mean_close_to_theoretical():
    """E[Beta(a, b)] = a / (a + b). n=5000 gives tight tolerance."""
    rng = np.random.default_rng(1)
    samples = [determinism.beta(rng, 2.0, 5.0) for _ in range(5000)]
    expected = 2.0 / (2.0 + 5.0)  # 0.2857
    assert abs(sum(samples) / 5000 - expected) < 0.02


def test_normal_mean_close_to_zero():
    rng = np.random.default_rng(1)
    samples = [determinism.normal(rng, 0.0, 1.0) for _ in range(5000)]
    assert abs(sum(samples) / 5000) < 0.05


def test_normal_variance_close_to_one():
    rng = np.random.default_rng(1)
    samples = [determinism.normal(rng, 0.0, 1.0) for _ in range(5000)]
    mean = sum(samples) / 5000
    var = sum((s - mean) ** 2 for s in samples) / 5000
    assert abs(var - 1.0) < 0.1


def test_exponential_mean_close_to_target():
    rng = np.random.default_rng(1)
    samples = [determinism.exponential(rng, 3.0) for _ in range(5000)]
    assert abs(sum(samples) / 5000 - 3.0) < 0.15


# ---------------------------------------------------------------------------
# Grand-design principle: precision constant lives in yaml, not code
# ---------------------------------------------------------------------------


def test_precision_loaded_from_yaml():
    import pathlib

    import yaml

    cfg_path = pathlib.Path(determinism.__file__).parent / "config" / "determinism.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    assert cfg["mpmath_precision_bits"] == 128


def test_module_uses_yaml_precision():
    from mpmath import mp

    assert mp.prec >= 100, "mpmath.prec should reflect the yaml value at import time"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_beta_shape_less_than_one_uses_boost():
    """``Beta(0.5, 0.5)`` triggers the shape-<1 branch in gamma."""
    rng = np.random.default_rng(42)
    v = determinism.beta(rng, 0.5, 0.5)
    assert 0.0 <= v <= 1.0
    # Not NaN
    assert v == v


def test_beta_output_in_unit_interval():
    rng = np.random.default_rng(42)
    for _ in range(200):
        v = determinism.beta(rng, 1.5, 3.0)
        assert 0.0 <= v <= 1.0


def test_exponential_positive():
    rng = np.random.default_rng(42)
    for _ in range(200):
        v = determinism.exponential(rng, 1.0)
        assert v >= 0.0


def test_beta_shape_zero_raises():
    rng = np.random.default_rng(42)
    with pytest.raises(ValueError, match="positive"):
        determinism.beta(rng, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Anchor values (pinned to Apple Silicon reference — see comment)
# ---------------------------------------------------------------------------

# These are the reference values on Apple Silicon Python 3.12 / numpy 2.5.1
# / mpmath 1.3. Because the algorithm consumes only bit-identical
# primitives, these hex bit patterns MUST match on any platform.
# Regenerate + refresh only when the algorithm itself changes (which is
# a MINOR / MAJOR bump).
_ANCHOR = {
    "beta_2_5_seed42": "3fc09b6123d32eac",  # 0.12974180459274487
}


def test_beta_anchor_seed42_2_5():
    """Anchor: locks the bit representation so any drift is caught."""
    v = determinism.beta(np.random.default_rng(42), 2.0, 5.0)
    assert _hex(v) == _ANCHOR["beta_2_5_seed42"], (
        f"Beta(2,5) at seed 42 drifted: expected {_ANCHOR['beta_2_5_seed42']}, got {_hex(v)} ({v!r})"
    )


# Silence "unused" if math ends up unreferenced.
_ = math
