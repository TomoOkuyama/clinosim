"""FP-SEV-MODEL Task 6: inpatient uses the canonical category_from_score boundary
and no longer re-clamps minimum_severity locally (owned by sample_severity)."""

import inspect

import pytest

import clinosim.simulator.inpatient as ip

pytestmark = pytest.mark.unit


def test_inpatient_uses_category_from_score_helper():
    src = inspect.getsource(ip)
    assert "category_from_score(event.severity)" in src
    assert "event.severity > 0.7" not in src


def test_inpatient_no_longer_clamps_minimum_severity_locally():
    src = inspect.getsource(ip)
    assert "severity_order = [" not in src
