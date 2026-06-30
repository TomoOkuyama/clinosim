"""Imaging module engine (Tier 1 #2 PR1).

This file contains the reference data loaders + validators (Task 2) and the
enricher entry point (Task 4). Loaders are @lru_cache'd singletons (PR-B1
canonical form); validators fail-loud at import time (silent-no-op defense
Layer 3-6).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

# Canonical DICOM modality set (PR1 scope). Extension here triggers validators
# (forward + reverse coverage), so adding a modality is one-edit-one-check.
SUPPORTED_MODALITIES: frozenset[str] = frozenset({"CR", "CT"})

# Canonical body site set (PR1 scope).
SUPPORTED_BODY_SITES: frozenset[str] = frozenset({"chest", "head"})

# Canonical disease set with imaging coverage (PR1 scope).
SUPPORTED_IMAGING_DISEASES: frozenset[str] = frozenset({
    "bacterial_pneumonia", "aspiration_pneumonia", "hemorrhagic_stroke",
})


def _validate_modalities(data: dict[str, Any]) -> None:
    """Fail-loud validation of modalities.yaml (silent-no-op defense Layer 3-6)."""
    if not data:
        raise ValueError("modalities.yaml: empty top-level")
    modalities = data.get("modalities")
    if not modalities or not isinstance(modalities, dict):
        raise ValueError("modalities.yaml: missing or empty 'modalities' key")
    # Forward + reverse coverage against canonical set.
    yaml_keys = set(modalities.keys())
    if yaml_keys != set(SUPPORTED_MODALITIES):
        missing = SUPPORTED_MODALITIES - yaml_keys
        extra = yaml_keys - SUPPORTED_MODALITIES
        raise ValueError(
            f"modalities.yaml ↔ SUPPORTED_MODALITIES drift: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    for mod_key, mod in modalities.items():
        if not mod.get("dicom_code"):
            raise ValueError(f"modalities.yaml[{mod_key}]: missing dicom_code")
        if not mod.get("display_en") or not mod.get("display_ja"):
            raise ValueError(f"modalities.yaml[{mod_key}]: display_en + display_ja required")
        # CR uses per-view range; CT uses per-series range.
        per_view = mod.get("typical_instances_per_view_range")
        per_series = mod.get("typical_instances_per_series_range")
        if per_view is None and per_series is None:
            raise ValueError(
                f"modalities.yaml[{mod_key}]: must define either "
                f"typical_instances_per_view_range or typical_instances_per_series_range"
            )
        if per_view is not None:
            if (not isinstance(per_view, list) or len(per_view) != 2
                    or per_view[0] > per_view[1] or per_view[0] < 1):
                raise ValueError(
                    f"modalities.yaml[{mod_key}].typical_instances_per_view_range: "
                    f"must be [low, high] with 1 <= low <= high"
                )
        if per_series is not None:
            if not isinstance(per_series, dict) or not per_series:
                raise ValueError(
                    f"modalities.yaml[{mod_key}].typical_instances_per_series_range: dict required"
                )
            for bs, rng in per_series.items():
                if (not isinstance(rng, list) or len(rng) != 2
                        or rng[0] > rng[1] or rng[0] < 1):
                    raise ValueError(
                        f"modalities.yaml[{mod_key}].typical_instances_per_series_range[{bs}]: "
                        f"must be [low, high] with 1 <= low <= high"
                    )


def _validate_body_sites(data: dict[str, Any]) -> None:
    """Fail-loud validation of body_sites.yaml (forward + reverse coverage)."""
    if not data:
        raise ValueError("body_sites.yaml: empty top-level")
    body_sites = data.get("body_sites")
    if not body_sites or not isinstance(body_sites, dict):
        raise ValueError("body_sites.yaml: missing or empty 'body_sites' key")
    yaml_keys = set(body_sites.keys())
    if yaml_keys != set(SUPPORTED_BODY_SITES):
        missing = SUPPORTED_BODY_SITES - yaml_keys
        extra = yaml_keys - SUPPORTED_BODY_SITES
        raise ValueError(
            f"body_sites.yaml ↔ SUPPORTED_BODY_SITES drift: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    for bs_key, bs in body_sites.items():
        if not bs.get("snomed"):
            raise ValueError(f"body_sites.yaml[{bs_key}]: missing snomed")
        if not bs.get("display_en") or not bs.get("display_ja"):
            raise ValueError(f"body_sites.yaml[{bs_key}]: display_en + display_ja required")
        pcs = bs.get("procedure_codes") or {}
        if not pcs:
            raise ValueError(f"body_sites.yaml[{bs_key}]: missing procedure_codes")
        for proc_key, proc in pcs.items():
            for required in ("loinc", "cpt", "jp_k_code", "display_en", "display_ja"):
                if not proc.get(required):
                    raise ValueError(
                        f"body_sites.yaml[{bs_key}].procedure_codes[{proc_key}]: missing {required}"
                    )


def _validate_impression_templates(data: dict[str, Any]) -> None:
    """Fail-loud validation of impression_templates.yaml.

    Forward-coverage: every SUPPORTED_IMAGING_DISEASES entry must have a templates
    bucket. Each disease × modality_body_site bucket must have either 'normal' or
    'abnormal' (or both). Each leaf must carry findings_en/ja + impression_en/ja.
    Reverse-coverage: no stale entries beyond SUPPORTED_IMAGING_DISEASES (silent-no-op
    defense Layer 4 staleness check).
    """
    if not data:
        raise ValueError("impression_templates.yaml: empty top-level")
    templates = data.get("templates")
    if not templates or not isinstance(templates, dict):
        raise ValueError("impression_templates.yaml: missing or empty 'templates' key")
    yaml_diseases = set(templates.keys())
    if not SUPPORTED_IMAGING_DISEASES.issubset(yaml_diseases):
        missing = SUPPORTED_IMAGING_DISEASES - yaml_diseases
        raise ValueError(
            f"impression_templates.yaml: missing disease entries: {sorted(missing)}"
        )
    extra = yaml_diseases - SUPPORTED_IMAGING_DISEASES
    if extra:
        raise ValueError(
            f"impression_templates.yaml: stale disease entries (no SUPPORTED_IMAGING_DISEASES match): {sorted(extra)}"
        )
    required_leaf_keys = ("findings_en", "findings_ja", "impression_en", "impression_ja")
    for disease, mod_bs_dict in templates.items():
        if not mod_bs_dict:
            raise ValueError(f"impression_templates.yaml[{disease}]: empty modality bucket")
        for mod_bs, variants in mod_bs_dict.items():
            if not variants:
                raise ValueError(
                    f"impression_templates.yaml[{disease}][{mod_bs}]: empty variants"
                )
            for kind in ("normal", "abnormal"):
                if kind in variants:
                    for k in required_leaf_keys:
                        if not variants[kind].get(k):
                            raise ValueError(
                                f"impression_templates.yaml[{disease}][{mod_bs}][{kind}]: missing {k}"
                            )
            if "normal" not in variants and "abnormal" not in variants:
                raise ValueError(
                    f"impression_templates.yaml[{disease}][{mod_bs}]: "
                    f"must have at least 'normal' or 'abnormal' variant"
                )


@lru_cache(maxsize=1)
def load_modalities() -> dict[str, Any]:
    """Load modalities.yaml + validate. Cached singleton."""
    with (_REF_DIR / "modalities.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_modalities(data)
    return data["modalities"]


@lru_cache(maxsize=1)
def load_body_sites() -> dict[str, Any]:
    """Load body_sites.yaml + validate. Cached singleton."""
    with (_REF_DIR / "body_sites.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_body_sites(data)
    return data["body_sites"]


@lru_cache(maxsize=1)
def load_impression_templates() -> dict[str, Any]:
    """Load impression_templates.yaml + validate. Cached singleton."""
    with (_REF_DIR / "impression_templates.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_impression_templates(data)
    return data["templates"]
