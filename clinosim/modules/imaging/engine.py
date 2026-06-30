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


# ---------------------------------------------------------------------------
# Canonical ID prefixes (writer-owned; Task 5 FHIR builders import from here).
# Shared constant pattern = silent-no-op defense Layer 2 (writer↔reader).
# ---------------------------------------------------------------------------
IMAGING_STUDY_ID_PREFIX = "imgst-"
ENDPOINT_ID_PREFIX = "endpoint-"
RADIOLOGY_REPORT_ID_PREFIX = "imgrpt-"


# ---------------------------------------------------------------------------
# POST_ENCOUNTER enricher: Order(IMAGING) → ImagingStudyRecord
# ---------------------------------------------------------------------------

import hashlib  # noqa: E402 — placed here to keep loader section clean

import numpy as np  # noqa: E402

from clinosim.modules._shared import get_attr_or_key as _o  # noqa: E402
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed  # noqa: E402
from clinosim.types.encounter import OrderStatus, OrderType  # noqa: E402
from clinosim.types.imaging import ImagingSeries, ImagingStudyRecord, RadiologyReport  # noqa: E402


def _study_uid_from(sub_seed: int, kind: str = "study") -> str:
    """Generate a deterministic DICOM-style UID from sub_seed.

    Format: "2.25.<integer>" — UUID-style root prefix per DICOM standard.
    """
    salt = f"imaging:{kind}:v1"
    digest = hashlib.sha256(f"{salt}|{sub_seed}".encode()).digest()[:8]
    n = int.from_bytes(digest, "big")
    return f"2.25.{n}"


def _body_site_key_from_snomed(snomed: str) -> str:
    """Reverse-lookup: SNOMED code → body_sites.yaml key (e.g. "chest" / "head").

    Raises ValueError for unknown codes (silent-no-op defense).
    """
    for key, defn in load_body_sites().items():
        if defn["snomed"] == snomed:
            return key
    raise ValueError(f"Unknown body site SNOMED: {snomed!r} — not in body_sites.yaml")


def _expand_views_to_series(
    order_modality: str,
    body_site_key: str,
    views: list[str],
    rng: np.random.Generator,
) -> list[ImagingSeries]:
    """Expand Order.imaging_views into ImagingSeries list with instance counts.

    CR (typical_instances_per_view_range): 1 series per view, range[low, high] instances.
    CT (typical_instances_per_series_range): 1 series per view-acquisition, large N instances.
    """
    modalities = load_modalities()
    body_sites = load_body_sites()
    mod_def = modalities[order_modality]
    body_site_snomed = body_sites[body_site_key]["snomed"]
    body_site_display = body_sites[body_site_key]["display_en"]

    series_list: list[ImagingSeries] = []

    if "typical_instances_per_view_range" in mod_def:
        # Per-view modality (CR): 1 series per view
        low, high = mod_def["typical_instances_per_view_range"]
        for i, view in enumerate(views, start=1):
            instance_count = int(rng.integers(low, high + 1))
            series_list.append(ImagingSeries(
                series_number=i,
                modality_code=order_modality,
                body_site_snomed=body_site_snomed,
                body_site_display=body_site_display,
                description=f"{view} view",
                instance_count=instance_count,
            ))
    elif "typical_instances_per_series_range" in mod_def:
        # Per-series modality (CT): 1 series per acquisition, body-site-specific range
        range_per_body = mod_def["typical_instances_per_series_range"]
        if body_site_key not in range_per_body:
            raise ValueError(
                f"modalities.yaml[{order_modality}].typical_instances_per_series_range "
                f"missing body site {body_site_key!r}"
            )
        low, high = range_per_body[body_site_key]
        for i, view in enumerate(views, start=1):
            instance_count = int(rng.integers(low, high + 1))
            series_list.append(ImagingSeries(
                series_number=i,
                modality_code=order_modality,
                body_site_snomed=body_site_snomed,
                body_site_display=body_site_display,
                description=f"{view} acquisition",
                instance_count=instance_count,
            ))

    return series_list


def _select_report_template(
    disease_id: str,
    modality: str,
    body_site_key: str,
    severity: str,
    abnormal_rate_by_severity: dict[str, float],
    rng: np.random.Generator,
) -> tuple[str, dict[str, Any]]:
    """Select normal/abnormal report template based on disease + severity.

    Returns (variant_kind, template_dict).
    Raises ValueError when disease × modality_body_site is missing (forward-coverage
    guard — silent-no-op defense).
    """
    templates = load_impression_templates()
    disease_templates = templates.get(disease_id, {})
    key = f"{modality}_{body_site_key}"
    bucket = disease_templates.get(key, {})
    if not bucket:
        raise ValueError(
            f"impression_templates.yaml missing disease={disease_id!r} "
            f"modality_body_site={key!r} — add entry or extend SUPPORTED_IMAGING_DISEASES"
        )
    # Severity → abnormal rate; "any" is a catch-all fallback.
    rate = abnormal_rate_by_severity.get(severity, abnormal_rate_by_severity.get("any", 0.0))
    is_abnormal = float(rng.random()) < rate
    variant = "abnormal" if is_abnormal else "normal"
    if variant not in bucket:
        # e.g. disease only defines "abnormal" with any:1.0 — use the only key.
        variant = next(iter(bucket.keys()))
    return variant, bucket[variant]


def imaging_enricher(ctx: Any) -> None:
    """POST_ENCOUNTER enricher: Order(IMAGING) → ImagingStudyRecord in extensions['imaging'].

    Per Order(IMAGING), derives a per-order sub-seed from
    (master_seed, ENRICHER_SEED_OFFSETS["imaging"], order.order_id) →
    creates a deterministic StudyInstanceUID, expands imaging_views to
    ImagingSeries with per-modality instance counts from modalities.yaml,
    and selects a report template from impression_templates.yaml based on
    disease_id + severity + abnormal_rate_by_severity from imaging_spec_meta.

    Cancelled Orders are skipped (AD-32 snapshot + revoked SR semantics).

    EnricherContext interface (POST_ENCOUNTER stage):
      ctx.master_seed  — int
      ctx.records      — list with exactly 1 CIFPatientRecord-like object
      ctx.config       — SimulatorConfig-like object
    """
    for record in ctx.records:
        orders = _o(record, "orders", []) or []
        imaging_orders = [
            o for o in orders
            if _o(o, "order_type") in (OrderType.IMAGING, "imaging")
            and _o(o, "status") not in (OrderStatus.CANCELLED, "cancelled")
            # Skip legacy IMAGING orders (pre-Task3) that lack imaging metadata.
            # Only orders emitted by place_imaging_orders() carry imaging_body_site_code.
            and (_o(o, "imaging_body_site_code", "") or "")
            and (_o(o, "imaging_modality", "") or "")
        ]
        if not imaging_orders:
            continue

        disease_id: str = _o(record, "disease_id", "") or ""
        severity: str = _o(record, "severity", "moderate") or "moderate"
        studies: list[ImagingStudyRecord] = list(
            (_o(record, "extensions", {}) or {}).get("imaging", [])
        )

        for idx, order in enumerate(imaging_orders, start=1):
            order_id: str = _o(order, "order_id", "") or ""
            sub_seed = derive_sub_seed(
                ctx.master_seed, ENRICHER_SEED_OFFSETS["imaging"], order_id
            )
            rng = np.random.default_rng(sub_seed)

            modality: str = _o(order, "imaging_modality", "") or ""
            body_site_snomed: str = _o(order, "imaging_body_site_code", "") or ""
            views: list[str] = list(_o(order, "imaging_views", []) or [])
            body_site_key = _body_site_key_from_snomed(body_site_snomed)

            series = _expand_views_to_series(modality, body_site_key, views, rng)
            # Attach deterministic per-series UID (sub_seed + 1-based index to avoid
            # same-as-study UID when only 1 series exists).
            for i, s in enumerate(series, start=1):
                s.series_uid = _study_uid_from(sub_seed + i, "series")

            study_uid = _study_uid_from(sub_seed, "study")

            # abnormal_rate_by_severity is carried on Order via imaging_spec_meta
            # (set by place_imaging_orders, Task 3 Step 5).
            spec_meta: dict[str, Any] = _o(order, "imaging_spec_meta", {}) or {}
            abnormal_rate: dict[str, float] = spec_meta.get("abnormal_rate_by_severity", {})

            _variant, template = _select_report_template(
                disease_id, modality, body_site_key, severity, abnormal_rate, rng,
            )

            encounter_id: str = _o(order, "encounter_id", "") or ""
            report = RadiologyReport(
                report_id=f"{RADIOLOGY_REPORT_ID_PREFIX}{encounter_id}-{idx}",
                status="final",
                findings_text=template["findings_en"],
                findings_text_ja=template["findings_ja"],
                impression_text=template["impression_en"],
                impression_text_ja=template["impression_ja"],
                # findings_codes: forward-compat slot — PR1 leaves empty.
            )

            study = ImagingStudyRecord(
                study_id=f"{IMAGING_STUDY_ID_PREFIX}{encounter_id}-{idx}",
                study_instance_uid=study_uid,
                encounter_id=encounter_id,
                patient_id=_o(order, "patient_id", "") or "",
                order_id=order_id,
                status="available",
                started_datetime=_o(order, "ordered_datetime"),
                modality_code=modality,
                body_site_snomed=body_site_snomed,
                series=series,
                endpoint_id=f"{ENDPOINT_ID_PREFIX}{study_uid}",
                report=report,
            )
            studies.append(study)

        # Write back — create extensions dict on SimpleNamespace stubs if absent.
        extensions = _o(record, "extensions", None)
        if extensions is None:
            record.extensions = {}
            extensions = record.extensions
        extensions["imaging"] = studies
