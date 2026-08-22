"""Imaging module engine (Tier 1 #2 PR1).

This file contains the reference data loaders + validators (Task 2) and the
enricher entry point (Task 4). Loaders are @lru_cache'd singletons (PR-B1
canonical form); validators fail-loud at import time (silent-no-op defense
Layer 3-6).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.types.encounter import OrderStatus, OrderType
from clinosim.types.imaging import ImagingSeries, ImagingStudyRecord, RadiologyReport

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

# Canonical DICOM modality set (PR1 scope). Extension here triggers validators
# (forward + reverse coverage), so adding a modality is one-edit-one-check.
SUPPORTED_MODALITIES: frozenset[str] = frozenset(
    {
        "CR",
        "CT",
        # CO-1 continuation: MR + US added — modalities.yaml carries
        # matching entries with DICOM code + display_en/ja.
        "MR",
        "US",
        # fix 4: XA (X-Ray Angiography — coronary angiography orders) +
        # ECG (electrocardiography — DICOM waveform modality; ED/cardiac workup
        # orders classified OrderType.IMAGING). Both are standard DICOM PS3.3
        # modality values; without them these orders stub-fell with no modality.
        "XA",
        "ECG",
    }
)

# Canonical body site set. CO-1 continuation: expanded from
# {chest, head} to 10 sites, each with SNOMED code + procedure_codes
# verified via NLM Clinical Table Search Service + AMA CPT 2024 + MHLW
# Source: JP 診療報酬点数表 令和6年 (JP procedure-reimbursement master, Reiwa 6).
SUPPORTED_BODY_SITES: frozenset[str] = frozenset(
    {
        "chest",
        "head",
        "abdomen",
        "kidney",
        "leg",
        "skin",
        "hand",
        "hip",
        "spine",
        "wrist",
    }
)

# Canonical disease set with imaging coverage.
# RM-5 (cycle-3 tail): expanded to include sepsis / heart failure /
# acute MI — all commonly workup with CXR.
# CO-1 continuation: expanded to 26 additional diseases with
# clinically-warranted imaging orders (see disease/*.yaml `imaging_orders`
# blocks and impression_templates.yaml for the paired coverage).
SUPPORTED_IMAGING_DISEASES: frozenset[str] = frozenset(
    {
        "bacterial_pneumonia",
        "aspiration_pneumonia",
        "hemorrhagic_stroke",
        "sepsis",
        "heart_failure_exacerbation",
        "acute_mi",
        # CO-1 continuation additions:
        "acute_appendicitis",
        "acute_cholecystitis",
        "acute_kidney_injury",
        "acute_pancreatitis",
        "asthma_exacerbation",
        "atrial_fibrillation_rvr",
        "cellulitis",
        "cerebral_infarction",
        "copd_exacerbation",
        "crush_injury_hand",
        "deep_vein_thrombosis",
        "diabetic_ketoacidosis",
        "electrical_injury",
        "fall_from_height",
        "gi_bleeding",
        "hip_fracture",
        "ileus",
        "industrial_burn_severe",
        "influenza",
        "liver_cirrhosis_decompensated",
        "pulmonary_embolism",
        "subdural_hematoma",
        "traffic_accident_severe",
        "urinary_tract_infection",
        "vertebral_compression_fracture",
        "wrist_fracture_surgical",
    }
)


def _canonicalize_display(name: str) -> str:
    """Normalize an imaging display_name for cross-order duplicate detection.

    Cosmetic differences (`Chest_Xray_PA_Lateral` vs `Chest X-ray PA and
    Lateral`) should not be treated as different orders when they land on
    the same encounter minute. Compares case-, separator- and
    whitespace-insensitively; strips a small connective-word set so
    `PA and Lateral` matches `PA Lateral`.

    Not a general text normaliser — scope is the dedup key for
    ``_bb_imaging_studies`` only (Issue #822 N-9 follow-up).
    """
    if not name:
        return ""
    s = str(name).lower().replace("_", " ").replace("-", " ")
    # Drop connective words that authors alternate between (e.g. `PA and
    # Lateral` vs `PA Lateral`), but keep clinically meaningful terms.
    _skip = {"and", "of", "with", "for"}
    tokens = [t for t in s.split() if t and t not in _skip]
    return " ".join(tokens)


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
            f"modalities.yaml ↔ SUPPORTED_MODALITIES drift: missing={sorted(missing)}, extra={sorted(extra)}"
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
            if not isinstance(per_view, list) or len(per_view) != 2 or per_view[0] > per_view[1] or per_view[0] < 1:
                raise ValueError(
                    f"modalities.yaml[{mod_key}].typical_instances_per_view_range: "
                    f"must be [low, high] with 1 <= low <= high"
                )
        if per_series is not None:
            if not isinstance(per_series, dict) or not per_series:
                raise ValueError(f"modalities.yaml[{mod_key}].typical_instances_per_series_range: dict required")
            for bs, rng in per_series.items():
                if not isinstance(rng, list) or len(rng) != 2 or rng[0] > rng[1] or rng[0] < 1:
                    raise ValueError(
                        f"modalities.yaml[{mod_key}].typical_instances_per_series_range[{bs}]: "
                        f"must be [low, high] with 1 <= low <= high"
                    )


def _code_in_data(system: str, code: str) -> bool:
    """Direct membership check in codes/data/<system>.yaml.

    `lookup()` returns the code itself as fallback for unknown entries (not
    None), so it can't distinguish "code exists" from "code absent". Direct
    `cs.codes` membership IS the authoritative check (same pattern as
    `hai/engine.py:_code_in_data`).
    """
    from clinosim.codes.loader import _load_system

    cs = _load_system(system)
    if cs is None:
        raise ValueError(
            f"_code_in_data: code system {system!r} not registered in "
            f"clinosim/codes/data/ — system itself is missing, not the code"
        )
    return code in cs.codes


def _validate_body_sites(data: dict[str, Any]) -> None:
    """Fail-loud validation of body_sites.yaml (forward + reverse coverage).

    AD-30 chain addition: every body site's `snomed` must resolve in
    codes/data/snomed-ct.yaml — safety net now that the CIF no longer carries
    a fallback display string for unresolvable codes.
    """
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
            f"body_sites.yaml ↔ SUPPORTED_BODY_SITES drift: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    for bs_key, bs in body_sites.items():
        if not bs.get("snomed"):
            raise ValueError(f"body_sites.yaml[{bs_key}]: missing snomed")
        if not _code_in_data("snomed-ct", bs["snomed"]):
            raise ValueError(f"body_sites.yaml[{bs_key}].snomed {bs['snomed']!r} not in codes/data/snomed-ct.yaml")
        if not bs.get("display_en") or not bs.get("display_ja"):
            raise ValueError(f"body_sites.yaml[{bs_key}]: display_en + display_ja required")
        pcs = bs.get("procedure_codes") or {}
        if not pcs:
            raise ValueError(f"body_sites.yaml[{bs_key}]: missing procedure_codes")
        for proc_key, proc in pcs.items():
            for required in ("loinc", "cpt", "jp_k_code", "display_en", "display_ja"):
                if not proc.get(required):
                    raise ValueError(f"body_sites.yaml[{bs_key}].procedure_codes[{proc_key}]: missing {required}")


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
        raise ValueError(f"impression_templates.yaml: missing disease entries: {sorted(missing)}")
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
                raise ValueError(f"impression_templates.yaml[{disease}][{mod_bs}]: empty variants")
            for kind in ("normal", "abnormal"):
                if kind in variants:
                    for k in required_leaf_keys:
                        if not variants[kind].get(k):
                            raise ValueError(f"impression_templates.yaml[{disease}][{mod_bs}][{kind}]: missing {k}")
            if "normal" not in variants and "abnormal" not in variants:
                raise ValueError(
                    f"impression_templates.yaml[{disease}][{mod_bs}]: must have at least 'normal' or 'abnormal' variant"
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
# Procedure code key resolution — single source of truth (silent-no-op defense
# Layer 2). Order engine + FHIR DR builder both import from here; do NOT
# duplicate the mapping inline at call sites (I-2 time bomb fix, 2026-06-30).
# ---------------------------------------------------------------------------


def _resolve_imaging_procedure_code_key(
    modality: str,
    body_site: str,
    views: list[str],
    contrast: bool,
) -> str:
    """Resolve (modality, body_site, views, contrast) → procedure_codes key.

    CO-1 continuation: expanded from PR1 chest+head scope to
    10 body sites × CR/CT/MR/US modalities. Mapping picks the closest
    procedure_codes entry defined in body_sites.yaml.
    """
    # CR (X-ray) — per-body-site view combinations
    if modality == "CR":
        if body_site == "chest":
            return "CR_PA_Lateral" if "Lateral" in views else "CR_PA"
        if body_site == "abdomen":
            return "CR_Supine_Upright" if len(views) >= 2 else "CR_AP"
        if body_site == "hand":
            return "CR_PA_Oblique_Lateral"
        if body_site in ("hip", "spine"):
            return "CR_AP_Lateral"
        if body_site == "wrist":
            return "CR_PA_Lateral_Oblique" if len(views) >= 3 else "CR_PA_Lateral"
    # CT — contrast is the discriminator; non-contrast is the default
    if modality == "CT":
        if body_site in ("chest", "abdomen"):
            return "CT_contrast" if contrast else "CT_non_contrast"
        if body_site == "head":
            return "CT_non_contrast" if not contrast else "CT"
        if body_site in ("hip", "spine"):
            return "CT_non_contrast"
    # MR — non-contrast is the standard variant (contrast MR reserved for future)
    if modality == "MR":
        if body_site in ("head", "spine"):
            return "MR_non_contrast"
    # US — single procedure per body site (doppler for leg, generic for the rest)
    if modality == "US":
        if body_site == "leg":
            return "US_Doppler"
        if body_site in ("abdomen", "kidney", "skin"):
            return "US"
    raise ValueError(
        f"Unsupported imaging combination: modality={modality} body_site={body_site} views={views} contrast={contrast}"
    )


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

    series_list: list[ImagingSeries] = []

    if "typical_instances_per_view_range" in mod_def:
        # Per-view modality (CR): 1 series per view
        low, high = mod_def["typical_instances_per_view_range"]
        for i, view in enumerate(views, start=1):
            instance_count = int(rng.integers(low, high + 1))
            series_list.append(
                ImagingSeries(
                    series_number=i,
                    modality_code=order_modality,
                    body_site_snomed=body_site_snomed,
                    description=f"{view} view",
                    instance_count=instance_count,
                )
            )
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
            series_list.append(
                ImagingSeries(
                    series_number=i,
                    modality_code=order_modality,
                    body_site_snomed=body_site_snomed,
                    description=f"{view} acquisition",
                    instance_count=instance_count,
                )
            )

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


#: Generic negative-findings radiology report content. Emitted whenever
#: the per-disease impression_templates.yaml lookup misses (stub_only /
#: template-lookup ValueError) so every ImagingStudy carries a report and
#: `_bb_diagnostic_reports` does not silent-drop the RAD DR (P1-11
#: consumer-side coverage fix, session 88j — 2,559 studies with 0 DR
#: (RAD) in production output). Facts-only: no acuity claim beyond "no
#: acute abnormal findings", no anatomic assumptions.
_GENERIC_NEG_FINDINGS_JA = "特記すべき異常所見なし。"
_GENERIC_NEG_FINDINGS_EN = "No acute abnormal findings within the imaged field."
_GENERIC_NEG_IMPRESSION_JA = "今回撮像範囲内に急性期異常所見を認めず。"
_GENERIC_NEG_IMPRESSION_EN = "No acute abnormal findings within the imaged range."


def _build_generic_negative_report(encounter_id: str, idx: int) -> RadiologyReport:
    """Radiology fallback report used by both stub_only and
    template-lookup ValueError paths (P1-11).

    Content is deliberately generic (chest / abdomen / head are not
    distinguished) since these paths hit precisely when we do not know
    the modality × body_site well enough to pick a template. Emitting
    "no acute findings" carries the same clinical meaning ("negative
    read within the acquired field") that a template's normal variant
    would — the diff is only that we cannot cite the anatomy back.
    """
    return RadiologyReport(
        report_id=f"{RADIOLOGY_REPORT_ID_PREFIX}{encounter_id}-{idx}",
        status="final",
        findings_text=_GENERIC_NEG_FINDINGS_EN,
        findings_text_ja=_GENERIC_NEG_FINDINGS_JA,
        impression_text=_GENERIC_NEG_IMPRESSION_EN,
        impression_text_ja=_GENERIC_NEG_IMPRESSION_JA,
    )


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
    # Lazy import to avoid circular dependency with seeding module.
    # Lazy import to avoid circular dep with inference module (which imports
    # load_body_sites / load_modalities from this module).
    from clinosim.modules.imaging.inference import infer_imaging_metadata
    from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed

    for record in ctx.records:
        orders = _o(record, "orders", []) or []
        # Case-D fix (CIF-VS-FHIR-01): removed the requirement that
        # ``imaging_body_site_code`` / ``imaging_modality`` be present
        # at the gate. Orders without metadata are handled inside the
        # loop by ``display_name`` inference or a stub fallback, so
        # every imaging order maps to an ``ImagingStudy`` and no
        # silent drop occurs.
        imaging_orders = [
            o
            for o in orders
            if _o(o, "order_type") in (OrderType.IMAGING, "imaging")
            and _o(o, "status") not in (OrderStatus.CANCELLED, "cancelled")
        ]
        if not imaging_orders:
            continue

        # disease_id: stored in extensions._disease_id by inpatient simulation
        # (Task 8 fix: enrichers run after record creation, disease_id not in CIF core).
        # Fallback to direct record.disease_id for tests (SimpleNamespace fixtures).
        extensions = _o(record, "extensions", {}) or {}
        disease_id: str = extensions.get("_disease_id", "") or _o(record, "disease_id", "") or ""
        severity: str = _o(record, "severity", "moderate") or "moderate"
        studies: list[ImagingStudyRecord] = list((_o(record, "extensions", {}) or {}).get("imaging", []))

        for idx, order in enumerate(imaging_orders, start=1):
            order_id: str = _o(order, "order_id", "") or ""
            sub_seed = derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["imaging"], order_id)
            rng = np.random.default_rng(sub_seed)

            modality: str = _o(order, "imaging_modality", "") or ""
            body_site_snomed: str = _o(order, "imaging_body_site_code", "") or ""
            views: list[str] = list(_o(order, "imaging_views", []) or [])
            # Case-D fix: infer metadata from ``display_name`` when the
            # order lacks it. On failure, emit a minimal ImagingStudy
            # with ``stub_only=True`` (see below).
            stub_only = False
            if not (modality and body_site_snomed):
                inferred = infer_imaging_metadata(_o(order, "display_name", "") or "")
                if inferred:
                    modality = inferred["modality"]
                    body_site_snomed = inferred["body_site_snomed"]
                    if not views:
                        views = list(inferred.get("views", []))
                else:
                    stub_only = True
            body_site_key = _body_site_key_from_snomed(body_site_snomed) if body_site_snomed else ""

            # Case-D fix: if the inferred metadata fails
            # ``modalities.yaml`` validation (e.g. ``US`` + ``chest`` =
            # Echocardiogram, but ``modalities.yaml`` does not register
            # ``chest`` under the ``US`` body_site), fall through to
            # the stub.
            if not stub_only and modality and body_site_key:
                try:
                    _test_series = _expand_views_to_series(modality, body_site_key, views, rng)
                except (ValueError, KeyError):
                    stub_only = True

            # Issue #822 (N-9) dedup — applies to BOTH stub-only and
            # non-stub paths (follow-up: the original PR #825 only wired
            # the stub-only branch, so non-stub cosmetic duplicates like
            # `Chest_Xray_PA_Lateral` + `Chest X-ray PA and Lateral`
            # ordered at the same minute both emitted). Skip this order
            # if a prior study in the same encounter already covers this
            # (started_datetime, canonicalized display_name) tuple.
            # Canonicalization = lowercase + strip + `_`/`-`→space +
            # collapsed whitespace, so cosmetic variants of the same
            # test name normalize to the same key.
            _stub_display = _o(order, "display_name", "") or ""
            _stub_started = _o(order, "ordered_datetime")
            _canon = _canonicalize_display(_stub_display)
            _dup = any(
                prev.encounter_id == (_o(order, "encounter_id", "") or "")
                and prev.started_datetime == _stub_started
                and _canonicalize_display(prev.description) == _canon
                for prev in studies
            )
            if _dup:
                continue

            # stub-only path: build minimum spec-valid ImagingStudy (no series /
            # modality unknown / description = display_name)。JP Core ImagingStudy
            # FHIR R4 ImagingStudy does not require ``series`` or ``modality``,
            # so a stub with neither is still spec-compliant.
            if stub_only:
                encounter_id_stub: str = _o(order, "encounter_id", "") or ""

                stub_uid = _study_uid_from(sub_seed, "study")
                stub_study = ImagingStudyRecord(
                    study_id=f"{IMAGING_STUDY_ID_PREFIX}{encounter_id_stub}-{idx}",
                    study_instance_uid=stub_uid,
                    encounter_id=encounter_id_stub,
                    patient_id=_o(order, "patient_id", "") or "",
                    order_id=order_id,
                    status="available",
                    started_datetime=_stub_started,
                    modality_code="",  # Inference failed.
                    body_site_snomed="",
                    series=[],  # 0 series is spec-valid for FHIR R4 ImagingStudy.
                    endpoint_id="",  # No PACS reference.
                    contrast=False,
                    # P1-11 (session 88j): emit generic negative-findings
                    # report instead of None so consumers get a RAD DR
                    # for every ImagingStudy. Prior behaviour left
                    # 2,559/2,559 studies without a report in JP p=10000
                    # cohorts (0.0% coverage).
                    report=_build_generic_negative_report(encounter_id_stub, idx),
                    # Issue #822 (N-9): carry the order's display_name so
                    # FHIR ImagingStudy.description is informative even
                    # when metadata inference failed. Reader UIs default
                    # empty description to the generic "画像検査"
                    # placeholder — populating it here removes both the
                    # placeholder and the visual duplication cue.
                    description=_stub_display,
                )
                studies.append(stub_study)
                continue

            series = _expand_views_to_series(modality, body_site_key, views, rng)
            # Attach deterministic per-series UID (sub_seed + 1-based index to avoid
            # same-as-study UID when only 1 series exists).
            for i, s in enumerate(series, start=1):
                s.series_uid = _study_uid_from(sub_seed + i, "series")

            study_uid = _study_uid_from(sub_seed, "study")

            # abnormal_rate_by_severity + contrast are carried on Order via imaging_spec_meta
            # (set by place_imaging_orders, Task 3 Step 5 + I-2 fix 2026-06-30).
            spec_meta: dict[str, Any] = _o(order, "imaging_spec_meta", {}) or {}
            abnormal_rate: dict[str, float] = spec_meta.get("abnormal_rate_by_severity", {})
            contrast: bool = bool(spec_meta.get("contrast", False))

            # Case-D fix: if the template lookup fails (empty
            # disease_id + an unregistered modality_body_site
            # combination — e.g. the ED / unknown_condition path), emit
            # the study only (``report=None``); that preserves meaning
            # better than a silent drop.
            try:
                _variant, template = _select_report_template(
                    disease_id,
                    modality,
                    body_site_key,
                    severity,
                    abnormal_rate,
                    rng,
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
            except ValueError:
                # Template unregistered → P1-11 (session 88j): emit
                # generic negative-findings report instead of None so
                # the ED / unknown_condition path still gets a RAD DR.
                # Prior behaviour silent-dropped these studies from the
                # DR (RAD) pipeline via _bb_diagnostic_reports's
                # ``if report:`` gate.
                encounter_id = _o(order, "encounter_id", "") or ""
                report = _build_generic_negative_report(encounter_id, idx)

            # Issue #822 follow-up: non-stub studies were the majority of
            # the 916 / 4863 (18.8%) empty-description hits in the deployed
            # cohort — PR #825 only wired the stub-only branch.
            # emit-time (imaging_study.py) prefers the body_sites-driven
            # `_proc_display` when the (modality, body_site, contrast)
            # tuple matches a `procedure_codes` entry, and falls back to
            # `study.description` otherwise. Populating it from
            # `order.display_name` here mirrors the stub-only fallback so
            # the emit is never empty even when the primary lookup misses.
            _non_stub_display = _o(order, "display_name", "") or ""
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
                contrast=contrast,
                report=report,
                description=_non_stub_display,
            )
            studies.append(study)

        # Write back — create extensions dict on SimpleNamespace stubs if absent.
        extensions = _o(record, "extensions", None)
        if extensions is None:
            record.extensions = {}
            extensions = record.extensions
        extensions["imaging"] = studies

    # _disease_id IPC cleanup moved to inpatient.py (I-6 fix, 2026-06-30).
    # Cleanup now fires unconditionally after run_stage() returns so it is
    # exception-safe and accessible to future POST_ENCOUNTER enrichers at order > 90.
