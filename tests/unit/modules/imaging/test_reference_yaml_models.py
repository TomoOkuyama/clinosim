"""The imaging reference YAML models reject every malformed shape (Issue #2568)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel

from clinosim.datafiles import load_data_yaml
from clinosim.modules.imaging.engine import _REF_DIR, ImagingBodySites, ImagingModalities, ImpressionTemplates

pytestmark = pytest.mark.unit

_Break = Callable[[dict[str, Any]], Any]


def _shipped(name: str) -> dict[str, Any]:
    return copy.deepcopy(load_data_yaml(_REF_DIR / name))


def _rejects(model: type[BaseModel], name: str, break_it: _Break, message: str) -> None:
    data = _shipped(name)
    break_it(data)
    with pytest.raises(ValueError, match=message):
        model.model_validate(data)


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (ImagingModalities, "modalities.yaml"),
        (ImagingBodySites, "body_sites.yaml"),
        (ImpressionTemplates, "impression_templates.yaml"),
    ],
)
def test_shipped_yaml_is_accepted(model: type[BaseModel], name: str) -> None:
    model.model_validate(_shipped(name))


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda d: d.clear(), "empty top-level"),
        (lambda d: d.update({"modalities": {}}), "modalities"),
        (lambda d: d["modalities"].pop("CT"), "SUPPORTED_MODALITIES drift"),
        (lambda d: d["modalities"].update({"PET": d["modalities"]["CR"]}), "SUPPORTED_MODALITIES drift"),
        (lambda d: d["modalities"]["CR"].update({"dicom_code": ""}), "dicom_code"),
        (lambda d: d["modalities"]["CR"].pop("typical_instances_per_view_range"), "must define either"),
        (lambda d: d["modalities"]["CR"].update({"typical_instances_per_view_range": [2, 1]}), r"\[low, high\]"),
        (lambda d: d["modalities"]["CR"].update({"typical_instances_per_view_range": [0, 1]}), r"\[low, high\]"),
        (lambda d: d["modalities"]["CR"].update({"typical_instances_per_view_range": [1]}), r"\[low, high\]"),
        (lambda d: d["modalities"]["CT"].update({"typical_instances_per_series_range": {}}), "non-empty dict"),
        (
            lambda d: d["modalities"]["CT"]["typical_instances_per_series_range"].update({"chest": [5, 1]}),
            r"\[low, high\]",
        ),
    ],
)
def test_modalities_rejections(break_it: _Break, message: str) -> None:
    _rejects(ImagingModalities, "modalities.yaml", break_it, message)


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda d: d.clear(), "empty top-level"),
        (lambda d: d.update({"body_sites": {}}), "body_sites"),
        (lambda d: d["body_sites"].pop("chest"), "SUPPORTED_BODY_SITES drift"),
        (lambda d: d["body_sites"]["chest"].update({"snomed": ""}), "missing snomed"),
        (lambda d: d["body_sites"]["chest"].update({"snomed": "99999999999"}), "99999999999"),
        (lambda d: d["body_sites"]["chest"].pop("procedure_codes"), "procedure_codes"),
        (lambda d: d["body_sites"]["chest"].update({"procedure_codes": {}}), "procedure_codes"),
        (lambda d: next(iter(d["body_sites"]["chest"]["procedure_codes"].values())).pop("cpt"), "cpt"),
        (lambda d: next(iter(d["body_sites"]["chest"]["procedure_codes"].values())).update({"loinc": ""}), "loinc"),
        (
            lambda d: next(iter(d["body_sites"]["chest"]["procedure_codes"].values())).pop("jp_k_code"),
            "jp_k_code",
        ),
    ],
)
def test_body_sites_rejections(break_it: _Break, message: str) -> None:
    _rejects(ImagingBodySites, "body_sites.yaml", break_it, message)


def _first_bucket(d: dict[str, Any]) -> dict[str, Any]:
    return next(iter(d["templates"]["bacterial_pneumonia"].values()))


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda d: d.clear(), "empty top-level"),
        (lambda d: d.update({"templates": {}}), "templates"),
        (lambda d: d["templates"].pop("bacterial_pneumonia"), "missing disease entries"),
        (lambda d: d["templates"].update({"no_such_disease": {}}), "stale disease entries"),
        (lambda d: d["templates"].update({"bacterial_pneumonia": {}}), "empty modality bucket"),
        (lambda d: d["templates"]["bacterial_pneumonia"].update({"CR_chest": {}}), "'normal' or 'abnormal'"),
        (lambda d: _first_bucket(d)["normal"].pop("findings"), "findings"),
        (lambda d: _first_bucket(d)["normal"]["impression"].update({"ja": ""}), "ja"),
        (lambda d: _first_bucket(d)["abnormal"]["findings"].pop("en"), "en"),
    ],
)
def test_impression_templates_rejections(break_it: _Break, message: str) -> None:
    _rejects(ImpressionTemplates, "impression_templates.yaml", break_it, message)
