"""NEWS2 total Observations carry LOINC 115635-5 (Early warning score) for US cohorts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

pytestmark = pytest.mark.unit


def _news2_obs(country: str) -> dict:
    ctx = SimpleNamespace(
        record={"encounters": [], "vital_signs": [{"timestamp": "2026-05-12T10:00:00", "news2_score": 5}]},
        country=country,
        patient_id="POP-000001",
        primary_enc_id="ENC-001",
    )
    obs = [o for o in _bb_nursing_observations(ctx) if o["valueInteger"] == 5 and o["id"].startswith("news2-")]
    assert len(obs) == 1
    return obs[0]


def test_us_news2_has_loinc_and_keeps_local_code() -> None:
    codings = _news2_obs("US")["code"]["coding"]
    assert {"system": "http://loinc.org", "code": "115635-5", "display": "Early warning score EWS"} in codings
    assert any(c["code"] == "NEWS2" for c in codings)


def test_jp_news2_unchanged() -> None:
    codings = _news2_obs("JP")["code"]["coding"]
    assert [c["code"] for c in codings] == ["NEWS2"]
