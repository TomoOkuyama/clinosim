"""``clinosim eval --only-axes`` flag unit tests.

Locks in the invariant that ``--only-axes`` restricts the axis filter
without breaking the default (flag-omitted) behavior. Added alongside
the JP-CLINS lab compliance CI gate (Issue #410); the gate depends on
this flag, so the flag itself needs an independent safety net.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.eval.engine import EvalEngine


def _minimal_flat_cohort(root: Path) -> None:
    """One Patient resource under fhir_r4/, enough for engine.run() to succeed."""
    (root / "fhir_r4").mkdir(parents=True, exist_ok=True)
    with (root / "fhir_r4" / "Patient.ndjson").open("w") as f:
        f.write(json.dumps({"resourceType": "Patient", "id": "p1"}) + "\n")


@pytest.mark.unit
def test_default_runs_all_registered_axes(tmp_path: Path) -> None:
    _minimal_flat_cohort(tmp_path)
    report = EvalEngine(cohort_dir=tmp_path).run()
    axis_names = {a.axis for a in report.axes}
    assert axis_names == {"structural", "clinical", "locale", "jp_clins_lab_compliance"}


@pytest.mark.unit
def test_only_axes_restricts_to_named_axis(tmp_path: Path) -> None:
    _minimal_flat_cohort(tmp_path)
    report = EvalEngine(cohort_dir=tmp_path, only_axes=["jp_clins_lab_compliance"]).run()
    axis_names = {a.axis for a in report.axes}
    assert axis_names == {"jp_clins_lab_compliance"}


@pytest.mark.unit
def test_only_axes_accepts_multiple(tmp_path: Path) -> None:
    _minimal_flat_cohort(tmp_path)
    report = EvalEngine(cohort_dir=tmp_path, only_axes=["clinical", "locale"]).run()
    axis_names = {a.axis for a in report.axes}
    assert axis_names == {"clinical", "locale"}


@pytest.mark.unit
def test_only_axes_rejects_unknown_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown axis id"):
        EvalEngine(cohort_dir=tmp_path, only_axes=["no_such_axis"])


@pytest.mark.unit
def test_only_axes_rejects_partial_unknown(tmp_path: Path) -> None:
    # Even if one id is valid, an unknown sibling must fail fast — never
    # silently drop the typo.
    with pytest.raises(ValueError, match="unknown axis id"):
        EvalEngine(cohort_dir=tmp_path, only_axes=["clinical", "typo_axis"])
