"""Issue #2815: MAR refusal and timing jitter come from hashes, so the number
of administrations shifts no draw of the stay's stream."""

from __future__ import annotations

import statistics

import pytest

from clinosim import determinism

pytestmark = pytest.mark.unit


def test_sha_normal_is_deterministic() -> None:
    assert determinism.sha_normal("a|b", 5.0, 10.0) == determinism.sha_normal("a|b", 5.0, 10.0)
    assert determinism.sha_normal("a|b", 5.0, 10.0) != determinism.sha_normal("a|c", 5.0, 10.0)


def test_sha_normal_has_the_stated_mean_and_sd() -> None:
    xs = [determinism.sha_normal(f"salt-{i}", 5.0, 10.0) for i in range(20000)]
    assert abs(statistics.fmean(xs) - 5.0) < 0.3
    assert abs(statistics.pstdev(xs) - 10.0) < 0.3


def test_mar_draws_do_not_consume_the_stream() -> None:
    """Generating the MAR leaves the stay's stream where the per-order draws
    alone put it: refusal and jitter take nothing from it."""
    import inspect

    from clinosim.simulator import medication_pipeline

    src = inspect.getsource(medication_pipeline._generate_mar)
    assert "rng.random() < MAR_PATIENT_REFUSAL_PROBABILITY" not in src
    assert "rng.normal(MAR_JITTER_MEAN_MIN" not in src
