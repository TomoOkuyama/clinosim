"""JP stage, stage type and clinical-impression severity are Japanese (Issue #3032)."""

from __future__ import annotations

import glob
import re

import pytest
import yaml

from clinosim.locale.i18n import t
from clinosim.locale.loader import condition_stage_display
from clinosim.modules.output.fhir_r4.conditions.conditions import _stage

pytestmark = pytest.mark.unit

_ENGLISH_WORD = re.compile(r"[a-z]{3,}")


@pytest.mark.parametrize(
    ("stage", "ja"),
    [
        ("Stage 1", "ステージ1"),
        ("Mild persistent", "軽症持続型"),
        ("PHQ-9 moderate", "PHQ-9 中等度"),
        ("Paroxysmal", "発作性"),
        ("AJCC III", "III期"),
        ("NYHA II", "NYHA II度"),
    ],
)
def test_a_jp_stage_summary_is_japanese(stage: str, ja: str) -> None:
    (entry,) = _stage(stage, "JP")
    assert entry["summary"]["text"] == ja
    assert entry["type"]["text"] == "臨床病期"


def test_a_us_stage_is_unchanged() -> None:
    (entry,) = _stage("Mild persistent", "US")
    assert entry["summary"]["text"] == "Mild persistent"
    assert entry["type"]["text"] == "Clinical stage"


def test_the_snomed_coding_stays_english() -> None:
    (entry,) = _stage("NYHA II", "JP")
    for coding in entry["summary"].get("coding", []):
        assert not re.search(r"[぀-ヿ一-鿿]", coding.get("display", ""))


def _stage_labels() -> set[str]:
    labels: set[str] = set()
    for path in glob.glob("clinosim/locale/shared/longitudinal/stage/*.yaml"):
        labels |= set(yaml.safe_load(open(path)).get("states") or [])
    severity = yaml.safe_load(open("clinosim/modules/patient/reference_data/stage_severity.yaml"))["stage_severity"]
    for stages in severity.values():
        labels |= set(stages)
    return labels


def test_every_stage_label_has_a_japanese_display() -> None:
    from clinosim.locale.loaders.narrative import load_condition_stage_labels

    table = load_condition_stage_labels()
    assert [s for s in sorted(_stage_labels()) if not (table.get(s) or {}).get("ja")] == []
    # Japanese labels keep Latin script only for scale names (Child-Pugh,
    # Hoehn-Yahr), never English words.
    words = {w for s in _stage_labels() for w in _ENGLISH_WORD.findall(condition_stage_display(s, "ja"))}
    assert words <= {"hild", "ugh", "oehn", "ahr"}, words


@pytest.mark.parametrize(("severity", "ja"), [("mild", "軽症"), ("moderate", "中等症"), ("severe", "重症")])
def test_a_jp_impression_names_the_severity_in_japanese(severity: str, ja: str) -> None:
    from clinosim.modules.document.engine import _severity_label

    assert _severity_label(severity, "ja") == ja
    assert _severity_label(severity, "en") == severity
    assert ja in t("clinical_impression.sev_part", "ja", severity=_severity_label(severity, "ja"))
