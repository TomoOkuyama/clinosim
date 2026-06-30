"""Verify disease YAML imaging_orders[] field parses + carries expected entries."""

from __future__ import annotations

from clinosim.modules.disease.protocol import load_disease_protocol


def test_bacterial_pneumonia_has_cr_chest_and_ct_chest():
    p = load_disease_protocol("bacterial_pneumonia")
    assert len(p.imaging_orders) >= 2
    modalities = [io.modality for io in p.imaging_orders]
    assert "CR" in modalities
    assert "CT" in modalities


def test_aspiration_pneumonia_has_cr_chest_at_admission():
    p = load_disease_protocol("aspiration_pneumonia")
    cr = [io for io in p.imaging_orders if io.modality == "CR"]
    assert cr
    assert cr[0].day == 0
    assert cr[0].body_site == "chest"
    assert cr[0].views == ["PA", "Lateral"]


def test_hemorrhagic_stroke_has_stat_ct_head():
    p = load_disease_protocol("hemorrhagic_stroke")
    assert len(p.imaging_orders) == 1
    io = p.imaging_orders[0]
    assert io.modality == "CT"
    assert io.body_site == "head"
    assert io.urgency == "stat"
    assert io.day == 0
    assert io.abnormal_rate_by_severity == {"any": 1.0}


def test_bacterial_pneumonia_ct_chest_only_if_severe():
    p = load_disease_protocol("bacterial_pneumonia")
    ct = [io for io in p.imaging_orders if io.modality == "CT"]
    assert ct
    assert "moderate" in ct[0].only_if_severity or "severe" in ct[0].only_if_severity
