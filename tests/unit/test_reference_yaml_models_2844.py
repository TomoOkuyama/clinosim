"""Issue #2844: the last four plain-dict module reference YAMLs are validated
by ``extra="forbid"`` models. Each model accepts the shipped file and rejects
an unknown key and a broken value."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.observation._reference_models import LabAliases, LabConstants, NursingScores
from clinosim.modules.order.supersede import MedicationSupersede

pytestmark = pytest.mark.unit

_MODULES = Path(__file__).resolve().parents[2] / "clinosim" / "modules"
_SUPERSEDE = _MODULES / "order" / "reference_data" / "medication_supersede.yaml"
_OBS = _MODULES / "observation" / "reference_data"


def _data(path: Path) -> dict[str, Any]:
    return copy.deepcopy(load_data_yaml(path))


@pytest.mark.parametrize(
    ("model", "path"),
    [
        (MedicationSupersede, _SUPERSEDE),
        (LabAliases, _OBS / "lab_aliases.yaml"),
        (LabConstants, _OBS / "lab_constants.yaml"),
        (NursingScores, _OBS / "nursing_scores.yaml"),
    ],
)
def test_shipped_file_is_valid(model: type[BaseModel], path: Path) -> None:
    model.model_validate(load_data_yaml(path))


# --- unknown keys ----------------------------------------------------------


def test_supersede_rejects_unknown_key() -> None:
    data = _data(_SUPERSEDE)
    data["class_switch"] = []
    with pytest.raises(ValidationError, match="class_switch"):
        MedicationSupersede.model_validate(data)


def test_supersede_rule_rejects_unknown_key() -> None:
    data = _data(_SUPERSEDE)
    data["class_switches"][0]["stop"] = ["antibiotic.penicillin"]
    with pytest.raises(ValidationError, match="stop"):
        MedicationSupersede.model_validate(data)


def test_lab_constants_rejects_unknown_section() -> None:
    data = _data(_OBS / "lab_constants.yaml")
    data["biologic_cv"] = {"Na": 0.01}
    with pytest.raises(ValidationError, match="biologic_cv"):
        LabConstants.model_validate(data)


@pytest.mark.parametrize("section", [None, "news2", "gcs", "braden", "morse"])
def test_nursing_scores_rejects_unknown_key(section: str | None) -> None:
    data = _data(_OBS / "nursing_scores.yaml")
    (data if section is None else data[section])["typo_key"] = 1
    with pytest.raises(ValidationError, match="typo_key"):
        NursingScores.model_validate(data)


def test_nursing_barthel_item_rejects_unknown_key() -> None:
    data = _data(_OBS / "nursing_scores.yaml")
    data["barthel_items"][0]["loinc_code"] = "83184-2"
    with pytest.raises(ValidationError, match="loinc_code"):
        NursingScores.model_validate(data)


# --- broken values ---------------------------------------------------------


def test_supersede_rejects_unknown_drug_class() -> None:
    data = _data(_SUPERSEDE)
    data["class_switches"][0]["stops"] = ["antibiotic.penicilin"]
    with pytest.raises(ValidationError, match="not a class of any catalog drug"):
        MedicationSupersede.model_validate(data)


def test_lab_aliases_rejects_non_string_target() -> None:
    data = _data(_OBS / "lab_aliases.yaml")
    data["Troponin"] = ["Troponin_I"]
    with pytest.raises(ValidationError):
        LabAliases.model_validate(data)


def test_lab_aliases_rejects_chained_alias() -> None:
    data = _data(_OBS / "lab_aliases.yaml")
    data["Troponin_x"] = "Troponin"  # Troponin is itself an alias
    with pytest.raises(ValidationError, match="one step"):
        LabAliases.model_validate(data)


@pytest.mark.parametrize(
    ("section", "lab", "value", "match"),
    [
        ("biological_cv", "Na", -0.1, "greater than or equal"),
        ("analytical_cv", "Na", "0.01", "valid number"),
        ("precision", "Na", 1.5, "valid integer"),
        ("physiologic_limits", "Na", [200.0, 100.0], "low must be below high"),
        ("panic_thresholds", "K", [6.5, 2.5], "low must be below high"),
        ("panic_thresholds", "K", [None, None], "both cutoffs null"),
        ("baseline_normals", "NoSuchLab", 1.0, "without a unit"),
    ],
)
def test_lab_constants_rejects_broken_value(section: str, lab: str, value: Any, match: str) -> None:
    data = _data(_OBS / "lab_constants.yaml")
    data[section][lab] = value
    with pytest.raises(ValidationError, match=match):
        LabConstants.model_validate(data)


def test_nursing_scores_rejects_inconsistent_gcs_components() -> None:
    data = _data(_OBS / "nursing_scores.yaml")
    data["gcs"]["components"][15] = [4, 5, 5]
    with pytest.raises(ValidationError, match="not summing"):
        NursingScores.model_validate(data)


def test_nursing_scores_rejects_probability_above_one() -> None:
    data = _data(_OBS / "nursing_scores.yaml")
    data["morse"]["fall_history_probability_by_age"][0] = [0, 1.5]
    with pytest.raises(ValidationError):
        NursingScores.model_validate(data)


def test_nursing_scores_rejects_inverted_news2_band() -> None:
    data = _data(_OBS / "nursing_scores.yaml")
    data["news2"]["heart_rate"][0] = [50, 40, 3]
    with pytest.raises(ValidationError, match="band low above high"):
        NursingScores.model_validate(data)
