"""The monitoring table is validated by an extra="forbid" Pydantic model."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.modules.monitoring.mapping import _YAML_PATH, load_medication_monitoring

pytestmark = pytest.mark.unit


def _write(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    mutate(data["mappings"])
    p = tmp_path / "medication_monitoring.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_the_shipped_table_validates() -> None:
    assert load_medication_monitoring()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m["Warfarin"].update(per_visit_probabilty=1.0),  # misspelled key
        lambda m: m["Warfarin"]["monitoring"][0].update(interval_months=0),
        lambda m: m["Warfarin"]["monitoring"][0].update(lab="NoSuchLab"),
        lambda m: m["Warfarin"].update(drugs=["no_such_drug"]),
        lambda m: m["Warfarin"].update(per_visit_probability=1.5),
        lambda m: m["Warfarin"].update(monitoring=[]),
        lambda m: m["Warfarin"]["monitoring"][0]["rationale"].pop("ja"),
    ],
    ids=["unknown-key", "interval-0", "uncoded-lab", "unknown-drug", "probability-above-1", "no-labs", "no-ja"],
)
def test_a_bad_entry_fails_at_load(tmp_path: Path, mutate) -> None:
    with pytest.raises(ValueError):
        load_medication_monitoring(_write(tmp_path, mutate))
