"""Every imaging key a disease protocol can order resolves to a catalog study
(Issue #3113): a modality, a body site, a registered LOINC procedure code with
English and Japanese displays, and an exam display in both languages."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from clinosim.codes import code_exists, display
from clinosim.locale.loader import load_narrative_imaging
from clinosim.locale.table import ImagingExamTable
from clinosim.modules.imaging.engine import (
    _body_site_key_from_snomed,
    _expand_views_to_series,
    bedside_examination_names,
    imaging_procedure_loinc,
)
from clinosim.modules.imaging.inference import infer_imaging_metadata

pytestmark = pytest.mark.unit

_DISEASES = Path(__file__).resolve().parents[2] / "clinosim" / "modules" / "disease" / "reference_data"


def _walk(node: object, keys: set[str]) -> None:
    """Collect the imaging keys of a disease YAML: ``add_imaging`` entries,
    ``imaging`` lists (``{test: ...}`` or bare names) and ``type: imaging``
    trigger actions."""
    if isinstance(node, dict):
        if node.get("type") == "imaging" and isinstance(node.get("test"), str):
            keys.add(node["test"])
        for key, value in node.items():
            if key in ("add_imaging", "imaging") and isinstance(value, list):
                for item in value:
                    name = item.get("test") if isinstance(item, dict) else item
                    if isinstance(name, str):
                        keys.add(name)
            _walk(value, keys)
    elif isinstance(node, list):
        for item in node:
            _walk(item, keys)


def _protocol_imaging_keys() -> list[str]:
    keys: set[str] = set()
    for path in sorted(_DISEASES.glob("*.yaml")):
        _walk(yaml.safe_load(path.read_text()), keys)
    return sorted(keys - bedside_examination_names())


def test_the_walk_finds_the_protocol_imaging_keys() -> None:
    keys = _protocol_imaging_keys()
    assert {"Chest_Xray_PA", "CT_pulmonary_angiography", "MRI_brain", "TEE"} <= set(keys)


@pytest.mark.parametrize("key", _protocol_imaging_keys())
def test_protocol_imaging_key_resolves_to_a_catalog_study(key: str) -> None:
    meta = infer_imaging_metadata(key)
    assert meta, f"{key}: no imaging catalog entry"
    body_site = _body_site_key_from_snomed(meta["body_site_snomed"])
    _expand_views_to_series(meta["modality"], body_site, meta["views"], np.random.default_rng(0))
    loinc = imaging_procedure_loinc(meta["modality"], body_site, meta["views"], meta["contrast"])
    assert loinc and code_exists("loinc", loinc), f"{key}: no LOINC procedure code ({meta['modality']} {body_site})"
    assert display("loinc", loinc, "en") and display("loinc", loinc, "ja"), f"{key}: LOINC {loinc} display"
    table = ImagingExamTable("narrative_imaging.imaging", load_narrative_imaging)
    entries = [table.entries().get(c) for c in table.candidates(key)]
    entry = next((e for e in entries if isinstance(e, dict)), None)
    assert entry and entry.get("en") and entry.get("ja"), f"{key}: no en/ja exam display"


@pytest.mark.parametrize(
    ("key", "modality", "body_site", "loinc"),
    [
        ("CT_pulmonary_angiography", "CT", "chest", "79077-4"),
        ("CT_angiography_abdomen_pelvis", "CT", "abdomen_pelvis", "69908-2"),
        ("CT_angiography_head_neck_repeat", "CT", "head", "37498-3"),
        ("CT_Angiography_Head", "CT", "head", "37498-3"),
        ("CT_perfusion", "CT", "head", "39142-5"),
        ("TEE", "US", "heart", "85475-2"),
        ("CT_chest_abdomen_pelvis_with_contrast", "CT", "chest_abdomen_pelvis", "72254-6"),
    ],
)
def test_an_angiography_or_special_study_is_coded_for_its_region(
    key: str, modality: str, body_site: str, loinc: str
) -> None:
    meta = infer_imaging_metadata(key)
    assert meta and (meta["modality"], meta["body_site_key"]) == (modality, body_site)
    assert imaging_procedure_loinc(modality, body_site, meta["views"], meta["contrast"]) == loinc
