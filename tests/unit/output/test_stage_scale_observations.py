"""Unit tests for chronic-disease stage-scale Observation emit.

Covers:
- One Observation per (patient, scale) for G20/G35/I69.x/F00 when the
  corresponding ``chronic_conditions[].stage`` is populated.
- No emit when stage string is empty, unparseable, or the ICD base
  code is outside the four tracked scales.
- Value type per scale: mRS → valueInteger, CDR → valueDecimal, EDSS
  and H&Y → valueString.
- Anchor encounter: latest outpatient-followup at or before snapshot,
  falling back to any encounter at or before snapshot, then to the
  last encounter in the record.
- Dedup when a patient carries two conditions mapping to the same
  scale (both I69.1 and I69.3 both staged — the first wins).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id
from clinosim.modules.output.fhir_r4.labs.stage_scale_observations import (
    _SCALE_SPECS,
    _bb_stage_scale_observations,
    build_stage_scale_observations,
)

LOINC_MRS = _SCALE_SPECS["mrs"].loinc
LOINC_EDSS = _SCALE_SPECS["edss"].loinc
LOINC_CDR = _SCALE_SPECS["cdr"].loinc


def _enc_ref(cif_id: str) -> str:
    return f"Encounter/{resolve_encounter_id(cif_id)}"


def _codings(obs: dict) -> list[str]:
    return [c.get("code", "") for c in (obs.get("code") or {}).get("coding") or []]


def _by_scale(observations: list[dict]) -> dict[str, dict]:
    """Keyed by code.text so H&Y (code-less) is addressable alongside
    LOINC-coded scales."""
    return {(o.get("code") or {}).get("text", ""): o for o in observations}


def _patient(chronics: list[dict]) -> dict:
    return {"patient_id": "pt-1", "chronic_conditions": chronics}


def _enc(encounter_id: str, admit: str, encounter_type: str = "outpatient") -> dict:
    return {
        "encounter_id": encounter_id,
        "admission_datetime": admit,
        "encounter_type": encounter_type,
    }


def test_i69_3_emits_mrs_integer():
    obs = build_stage_scale_observations(
        _patient([{"code": "I69.3", "stage": "mRS 4"}]),
        [_enc("enc-1", "2025-04-01T09:00:00")],
        "2025-12-31",
    )
    assert len(obs) == 1
    assert obs[0]["valueInteger"] == 4
    assert LOINC_MRS in _codings(obs[0])
    assert obs[0]["encounter"]["reference"] == _enc_ref("enc-1")
    assert obs[0]["effectiveDateTime"].startswith("2025-04-01")


def test_i69_1_also_emits_mrs():
    obs = build_stage_scale_observations(
        _patient([{"code": "I69.1", "stage": "mRS 2"}]),
        [_enc("enc-1", "2024-06-15T10:00:00")],
        None,
    )
    assert len(obs) == 1
    assert obs[0]["valueInteger"] == 2
    assert LOINC_MRS in _codings(obs[0])


def test_g20_emits_hy_string_no_loinc():
    obs = build_stage_scale_observations(
        _patient([{"code": "G20", "stage": "H&Y 3"}]),
        [_enc("enc-1", "2025-01-10T09:00:00")],
        "2025-12-31",
    )
    assert len(obs) == 1
    assert obs[0]["valueString"] == "H&Y 3"
    assert _codings(obs[0]) == []  # H&Y: display-only, no authoritative LOINC
    assert (obs[0].get("code") or {}).get("text") == "Hoehn and Yahr stage"


def test_g35_emits_edss_banded_string():
    obs = build_stage_scale_observations(
        _patient([{"code": "G35", "stage": "EDSS 2.5-5"}]),
        [_enc("enc-1", "2025-02-20T11:00:00")],
        "2025-12-31",
    )
    assert len(obs) == 1
    assert obs[0]["valueString"] == "EDSS 2.5-5"
    assert LOINC_EDSS in _codings(obs[0])


def test_f00_emits_cdr_decimal():
    obs = build_stage_scale_observations(
        _patient([{"code": "F00", "stage": "CDR 0.5"}]),
        [_enc("enc-1", "2025-03-01T09:00:00")],
        "2025-12-31",
    )
    assert len(obs) == 1
    assert obs[0]["valueDecimal"] == pytest.approx(0.5)
    assert LOINC_CDR in _codings(obs[0])


def test_empty_stage_skipped():
    obs = build_stage_scale_observations(
        _patient([{"code": "G20", "stage": ""}]),
        [_enc("enc-1", "2025-01-10T09:00:00")],
        "2025-12-31",
    )
    assert obs == []


def test_unmapped_icd_skipped():
    obs = build_stage_scale_observations(
        _patient([{"code": "E11.9", "stage": "whatever"}, {"code": "I10", "stage": "Stage 2"}]),
        [_enc("enc-1", "2025-01-10T09:00:00")],
        "2025-12-31",
    )
    assert obs == []


def test_unparseable_mrs_skipped():
    obs = build_stage_scale_observations(
        _patient([{"code": "I69.3", "stage": "mRS garbage"}]),
        [_enc("enc-1", "2025-01-10T09:00:00")],
        "2025-12-31",
    )
    assert obs == []


def test_multiple_scales_one_patient_all_emit():
    obs = build_stage_scale_observations(
        _patient(
            [
                {"code": "I69.3", "stage": "mRS 2"},
                {"code": "G20", "stage": "H&Y 2"},
                {"code": "G35", "stage": "EDSS 5.5-7"},
                {"code": "F00", "stage": "CDR 1"},
            ]
        ),
        [_enc("enc-1", "2025-05-01T10:00:00")],
        "2025-12-31",
    )
    scales = _by_scale(obs)
    assert set(scales.keys()) == {
        "Modified Rankin Scale",
        "Hoehn and Yahr stage",
        "Expanded Disability Status Scale score",
        "Clinical Dementia Rating Global score",
    }


def test_dup_mrs_first_wins():
    obs = build_stage_scale_observations(
        _patient(
            [
                {"code": "I69.1", "stage": "mRS 5"},
                {"code": "I69.3", "stage": "mRS 1"},
            ]
        ),
        [_enc("enc-1", "2025-05-01T10:00:00")],
        "2025-12-31",
    )
    assert len(obs) == 1
    assert obs[0]["valueInteger"] == 5


def test_anchor_prefers_latest_outpatient_followup_before_snapshot():
    encs = [
        _enc("enc-ip", "2024-02-15T08:00:00", "inpatient"),
        _enc("enc-fup-early", "2024-07-01T09:00:00", "outpatient"),
        _enc("enc-fup-late", "2025-10-05T11:00:00", "outpatient"),
        _enc("enc-fup-after-snap", "2026-02-10T09:00:00", "outpatient"),
    ]
    obs = build_stage_scale_observations(
        _patient([{"code": "I69.3", "stage": "mRS 3"}]),
        encs,
        "2025-12-31",
    )
    assert obs[0]["encounter"]["reference"] == _enc_ref("enc-fup-late")


def test_anchor_falls_back_to_any_encounter_before_snapshot():
    encs = [
        _enc("enc-ip1", "2024-02-15T08:00:00", "inpatient"),
        _enc("enc-ip2", "2025-06-01T08:00:00", "inpatient"),
    ]
    obs = build_stage_scale_observations(
        _patient([{"code": "I69.3", "stage": "mRS 3"}]),
        encs,
        "2025-12-31",
    )
    assert obs[0]["encounter"]["reference"] == _enc_ref("enc-ip2")


def test_no_encounter_skips_encounter_ref():
    obs = build_stage_scale_observations(
        _patient([{"code": "I69.3", "stage": "mRS 3"}]),
        [],
        "2025-12-31",
    )
    assert len(obs) == 1
    assert "encounter" not in obs[0]
    assert "effectiveDateTime" not in obs[0]


def test_bundle_builder_wires_ctx_fields():
    from types import SimpleNamespace

    ctx = SimpleNamespace(
        record={"encounters": [_enc("enc-ctx", "2025-04-01T09:00:00")]},
        patient_data=_patient([{"code": "G20", "stage": "H&Y 2"}]),
        snapshot_date="2025-12-31",
    )
    out = _bb_stage_scale_observations(ctx)  # type: ignore[arg-type]
    assert len(out) == 1
    assert out[0]["valueString"] == "H&Y 2"
    assert out[0]["encounter"]["reference"] == _enc_ref("enc-ctx")


def test_identifier_round_trip():
    obs = build_stage_scale_observations(
        _patient([{"code": "I69.3", "stage": "mRS 3"}]),
        [_enc("enc-1", "2025-04-01T09:00:00")],
        "2025-12-31",
    )
    ident = obs[0]["identifier"][0]
    assert ident["value"] == "pt-1-mrs"
    assert ident["system"].endswith("stage-scale-observation-key")
