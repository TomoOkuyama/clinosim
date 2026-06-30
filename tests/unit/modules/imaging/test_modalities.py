"""Unit tests for clinosim.modules.imaging modalities YAML loader/validator."""

from __future__ import annotations

import pytest

from clinosim.modules.imaging.engine import load_modalities


def test_modalities_loads_cr_and_ct():
    m = load_modalities()
    assert "CR" in m
    assert "CT" in m


def test_modality_cr_has_required_fields():
    m = load_modalities()
    cr = m["CR"]
    assert cr["dicom_code"] == "CR"
    assert cr["display_en"] == "Plain X-ray"
    assert cr["display_ja"] == "単純X線撮影"
    # CR = 1 view = 1 instance
    assert cr["typical_instances_per_view_range"] == [1, 1]
    assert "chest" in cr["default_views_by_body_site"]


def test_modality_ct_has_per_body_site_instance_range():
    m = load_modalities()
    ct = m["CT"]
    assert ct["dicom_code"] == "CT"
    assert ct["typical_instances_per_series_range"]["head"] == [180, 280]
    assert ct["typical_instances_per_series_range"]["chest"] == [220, 340]


def test_modalities_cached_lru():
    """@lru_cache(maxsize=1) — 2 calls return same object."""
    assert load_modalities() is load_modalities()
