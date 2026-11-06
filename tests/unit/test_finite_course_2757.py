"""Issue #2757: finite discharge courses are not carried into the home medications."""

from __future__ import annotations

import pytest

from clinosim.simulator.helpers import is_finite_course

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("duration", "finite"),
    [(None, False), (0, False), (1, True), (7, True), (14, True), (15, False), (90, False), ("x", False)],
)
def test_finite_course_boundaries(duration: object, finite: bool) -> None:
    item = {"drug_name": "Aspirin"} if duration is None else {"drug_name": "Aspirin", "duration_days": duration}
    assert is_finite_course(item) is finite
