"""One definition of an acute-illness visit (Issues #3655 / #3657): the visit-note
reason table lists exactly the pediatric schedule's acute presentations."""

from __future__ import annotations

import pytest

from clinosim.datafiles import load_data_yaml
from clinosim.modules.document.narrative import _visit_reason
from clinosim.modules.pediatric.calendar import is_acute_illness_condition, load_pediatric_schedule

pytestmark = pytest.mark.unit


def test_visit_reason_acute_illness_list_equals_the_presentations() -> None:
    from pathlib import Path

    path = Path(_visit_reason.__file__).resolve().parents[1] / "reference_data" / "visit_reason_soap.yaml"
    by_condition = load_data_yaml(path)["visit_kinds"]["by_condition"]
    acute_in_notes = {cond for cond, kind in by_condition.items() if kind == "acute_illness"}
    disease_ids = {entry["disease_id"] for entry in load_pediatric_schedule().values()}
    presentations = {d for d in disease_ids if is_acute_illness_condition(d)}
    assert acute_in_notes == presentations and presentations
