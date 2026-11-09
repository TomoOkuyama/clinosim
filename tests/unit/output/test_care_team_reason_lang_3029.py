"""Issue #3029: the CareTeam reason is the chief complaint in the output language."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.encounters.care_team import _bb_care_teams

pytestmark = pytest.mark.unit

_ENC = {
    "encounter_id": "enc-1",
    "encounter_type": "inpatient",
    "attending_physician_id": "dr-1",
    "admission_datetime": "2025-03-01T10:00:00",
    "chief_complaint": "Worsening dyspnea, increased sputum production",
    "chief_complaint_ja": "呼吸困難の増悪、喀痰増加",
}


def _reason(country: str, enc: dict) -> str:
    ctx = SimpleNamespace(
        record={"patient": {"patient_id": "P1"}, "encounters": [enc]}, country=country, patient_id="P1", roster_map={}
    )
    [team] = _bb_care_teams(ctx)
    return team["reasonCode"][0]["text"]


def test_jp_care_team_reason_is_japanese() -> None:
    assert _reason("JP", _ENC) == "呼吸困難の増悪、喀痰増加"


def test_us_care_team_reason_is_unchanged() -> None:
    assert _reason("US", _ENC) == "Worsening dyspnea, increased sputum production"


def test_reason_without_a_chief_complaint_falls_back_to_the_localized_default() -> None:
    enc = {k: v for k, v in _ENC.items() if not k.startswith("chief_complaint")}
    assert _reason("JP", enc) == _reason("JP", {**enc, "chief_complaint": ""})
    assert _reason("JP", enc).isascii() is False
