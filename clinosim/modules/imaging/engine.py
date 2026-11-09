"""Imaging module engine (Tier 1 #2 PR1).

This file contains the reference data loaders + validators (Task 2) and the
enricher entry point (Task 4). Loaders are @lru_cache'd singletons (PR-B1
canonical form); validators fail-loud at import time (silent-no-op defense
Layer 3-6).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator, model_validator

from clinosim import determinism
from clinosim.codes import code_exists
from clinosim.datafiles import load_data_yaml, load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.locale.localized import localized
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
        "MG",  # Issue #2870: screening mammography
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
        "abdomen_pelvis",  # Issue #2654
        "kidney",
        "leg",
        "skin",
        "hand",
        "hip",
        "knee",
        "spine",
        "wrist",
        # Issue #2655
        "ankle",
        "foot",
        "shoulder",
        "heart",
        "coronary_artery",
        "carotid_artery",
        "biliary_tract",
        "urinary_bladder",
        # Issue #2657
        "cervical_spine",
        "lumbar_spine",
        "breast",  # Issue #2870
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
        # Issue #2870: the screening mammogram of the healthcare calendar.
        "mammography_screening",
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


# A YAML number (not a numeric string).
_Number = StrictInt | StrictFloat


def _exact_keys(keys: set[str], supported: frozenset[str], where: str) -> None:
    """Forward + reverse coverage against a canonical set (silent-no-op defense Layer 4)."""
    if keys != supported:
        missing, extra = supported - keys, keys - supported
        raise ValueError(f"{where} drift: missing={sorted(missing)}, extra={sorted(extra)}")


def _instance_range(value: list[_Number], where: str) -> list[_Number]:
    if len(value) != 2 or not 1 <= value[0] <= value[1]:
        raise ValueError(f"modalities.yaml {where}: must be [low, high] with 1 <= low <= high")
    return value


class ImagingImpressionKeywords(BaseModel):
    """Shape of imaging-impression-keywords.yaml: the radiology impression
    phrases that commit a report to Normal, and those that flag it Abnormal."""

    model_config = ConfigDict(extra="forbid")

    normal: list[str]
    abnormal: list[str]


class _Modality(BaseModel):
    """CR uses a per-view instance range, CT a per-series range per body site.
    Displays resolve from codes/data/dicom-modality.yaml (META #1805 Phase C)."""

    model_config = ConfigDict(extra="forbid")

    dicom_code: str = Field(min_length=1)
    # Issue #2999: minutes from the study start to the signed report.
    report_read_minutes: list[_Number]
    typical_instances_per_view_range: list[_Number] | None = None
    typical_instances_per_series_range: dict[str, list[_Number]] | None = None
    # Body-site key -> the views ordered when a spec names none (order engine).
    default_views_by_body_site: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("report_read_minutes")
    @classmethod
    def _read_range(cls, value: list[_Number]) -> list[_Number]:
        return _instance_range(value, "report_read_minutes")

    @field_validator("typical_instances_per_view_range")
    @classmethod
    def _view_range(cls, value: list[_Number] | None) -> list[_Number] | None:
        return None if value is None else _instance_range(value, "typical_instances_per_view_range")

    @field_validator("typical_instances_per_series_range")
    @classmethod
    def _series_ranges(cls, value: dict[str, list[_Number]] | None) -> dict[str, list[_Number]] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("modalities.yaml typical_instances_per_series_range: non-empty dict required")
        for body_site, rng in value.items():
            _instance_range(rng, f"typical_instances_per_series_range[{body_site}]")
        return value

    @model_validator(mode="after")
    def _has_an_instance_range(self) -> _Modality:
        if self.typical_instances_per_view_range is None and self.typical_instances_per_series_range is None:
            raise ValueError(
                "modalities.yaml: must define either "
                "typical_instances_per_view_range or typical_instances_per_series_range"
            )
        return self


class ImagingModalities(BaseModel):
    """Shape of modalities.yaml: exactly the SUPPORTED_MODALITIES, each with a
    DICOM code and an instance-count range (silent-no-op defense Layer 3-6)."""

    model_config = ConfigDict(extra="forbid")

    modalities: dict[str, _Modality] = Field(min_length=1)
    # Issue #2999: read time of a study whose modality could not be inferred.
    stub_report_read_minutes: list[_Number]

    @field_validator("stub_report_read_minutes")
    @classmethod
    def _stub_read_range(cls, value: list[_Number]) -> list[_Number]:
        return _instance_range(value, "stub_report_read_minutes")

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        if not data:
            raise ValueError("modalities.yaml: empty top-level")
        return data

    @field_validator("modalities")
    @classmethod
    def _supported_modalities(cls, modalities: dict[str, _Modality]) -> dict[str, _Modality]:
        _exact_keys(set(modalities), SUPPORTED_MODALITIES, "modalities.yaml ↔ SUPPORTED_MODALITIES")
        return modalities


class _ProcedureCodes(BaseModel):
    """Displays resolve from the LOINC authority (META #1805 Phase B.2)."""

    model_config = ConfigDict(extra="forbid")

    loinc: str = Field(min_length=1)
    cpt: str = Field(min_length=1)
    jp_k_code: str = Field(min_length=1)


class _BodySite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snomed: str
    procedure_codes: dict[str, _ProcedureCodes] = Field(min_length=1)
    # A left/right structure: the order picks a laterality.
    paired: bool = False
    # Body site whose impression template this one reuses (e.g. lumbar_spine -> spine).
    report_template_site: str | None = None

    @field_validator("snomed")
    @classmethod
    def _registered(cls, code: str) -> str:
        """AD-30 chain: the CIF carries no fallback display for an unresolvable code."""
        if not code:
            raise ValueError("body_sites.yaml: missing snomed")
        if not code_exists("snomed-ct", code, exact=True):
            raise ValueError(f"body_sites.yaml snomed {code!r} not in codes/data/snomed-ct.yaml")
        return code


class ImagingBodySites(BaseModel):
    """Shape of body_sites.yaml: exactly the SUPPORTED_BODY_SITES, each with a
    registered SNOMED code and LOINC / CPT / JP K-code procedure codes."""

    model_config = ConfigDict(extra="forbid")

    body_sites: dict[str, _BodySite] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        if not data:
            raise ValueError("body_sites.yaml: empty top-level")
        return data

    @field_validator("body_sites")
    @classmethod
    def _supported_body_sites(cls, body_sites: dict[str, _BodySite]) -> dict[str, _BodySite]:
        _exact_keys(set(body_sites), SUPPORTED_BODY_SITES, "body_sites.yaml ↔ SUPPORTED_BODY_SITES")
        return body_sites


class _LanguageText(BaseModel):
    """The CIF report has an English and a Japanese slot (Issue #2505)."""

    model_config = ConfigDict(extra="forbid")

    en: str = Field(min_length=1)
    ja: str = Field(min_length=1)


class _ReportText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: _LanguageText
    impression: _LanguageText


class _ReportVariants(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normal: _ReportText | None = None
    abnormal: _ReportText | None = None

    @model_validator(mode="after")
    def _has_a_variant(self) -> _ReportVariants:
        if self.normal is None and self.abnormal is None:
            raise ValueError("impression_templates.yaml: must have at least 'normal' or 'abnormal' variant")
        return self


class ImpressionTemplates(BaseModel):
    """Shape of impression_templates.yaml: a non-empty bucket for exactly the
    SUPPORTED_IMAGING_DISEASES (missing and stale entries both rejected), each
    modality x body site with a normal and/or abnormal findings + impression."""

    model_config = ConfigDict(extra="forbid")

    templates: dict[str, dict[str, _ReportVariants]] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        if not data:
            raise ValueError("impression_templates.yaml: empty top-level")
        return data

    @field_validator("templates")
    @classmethod
    def _supported_diseases(
        cls, templates: dict[str, dict[str, _ReportVariants]]
    ) -> dict[str, dict[str, _ReportVariants]]:
        diseases = set(templates)
        missing = SUPPORTED_IMAGING_DISEASES - diseases
        if missing:
            raise ValueError(f"impression_templates.yaml: missing disease entries: {sorted(missing)}")
        stale = diseases - SUPPORTED_IMAGING_DISEASES
        if stale:
            raise ValueError(
                "impression_templates.yaml: stale disease entries "
                f"(no SUPPORTED_IMAGING_DISEASES match): {sorted(stale)}"
            )
        empty = sorted(disease for disease, buckets in templates.items() if not buckets)
        if empty:
            raise ValueError(f"impression_templates.yaml{empty}: empty modality bucket")
        return templates


class _BedsideExaminations(BaseModel):
    """Shape of ``bedside_examinations.yaml`` (Issue #2796)."""

    model_config = ConfigDict(extra="forbid")
    examinations: list[str] = Field(min_length=1)

    @field_validator("examinations")
    @classmethod
    def _named(cls, names: list[str]) -> list[str]:
        if not all(n.strip() for n in names) or len(set(names)) != len(names):
            raise ValueError("examinations must be distinct, non-empty order names")
        return names


@lru_cache(maxsize=1)
def bedside_examination_names() -> frozenset[str]:
    """Order names on the imaging work-up list that are bedside examinations,
    not imaging studies (``reference_data/bedside_examinations.yaml``,
    Issue #2796). They get no ImagingStudy and no radiology report."""
    return frozenset(
        _BedsideExaminations.model_validate(load_data_yaml(_REF_DIR / "bedside_examinations.yaml")).examinations
    )


@lru_cache(maxsize=1)
def _load_modalities_yaml() -> dict[str, Any]:
    return load_validated_yaml(_REF_DIR / "modalities.yaml", ImagingModalities)


def load_modalities() -> dict[str, Any]:
    """Load modalities.yaml + validate. Cached singleton."""
    return _load_modalities_yaml()["modalities"]


def stub_report_read_minutes() -> list[_Number]:
    """Read-time range of a study whose modality could not be inferred (Issue #2999)."""
    return _load_modalities_yaml()["stub_report_read_minutes"]


def report_issued_datetime(started: datetime | None, modality: str, patient_id: str, order_id: str) -> datetime | None:
    """When the radiologist signs the report of a study (Issue #2999).

    The study start plus a read time uniform in the modality's
    ``report_read_minutes`` (``stub_report_read_minutes`` for an unknown
    modality), whole minutes, derived from the order by SHA-256 so no RNG
    stream is consumed. ``None`` when the study has no start time.
    """
    if started is None:
        return None
    mod = load_modalities().get(modality)
    lo, hi = mod["report_read_minutes"] if mod else stub_report_read_minutes()
    q = determinism.sha_quantile(f"imaging-report-read|{patient_id}|{order_id}")
    return started + timedelta(minutes=round(lo + q * (hi - lo)))


@lru_cache(maxsize=1)
def load_body_sites() -> dict[str, Any]:
    """Load body_sites.yaml + validate. Cached singleton."""
    return load_validated_yaml(_REF_DIR / "body_sites.yaml", ImagingBodySites)["body_sites"]


@lru_cache(maxsize=1)
def load_impression_templates() -> dict[str, Any]:
    """Load impression_templates.yaml + validate. Cached singleton."""
    return load_validated_yaml(_REF_DIR / "impression_templates.yaml", ImpressionTemplates)["templates"]


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
            # Issue #2699: two views (PA + lateral), a portable AP film, or a
            # single standing PA view are different studies.
            if "Lateral" in views:
                return "CR_PA_Lateral"
            return "CR_AP" if "AP" in views else "CR_PA"
        if body_site == "abdomen":
            return "CR_Supine_Upright" if len(views) >= 2 else "CR_AP"
        if body_site == "hand":
            return "CR_PA_Oblique_Lateral"
        if body_site in ("hip", "knee", "spine", "shoulder", "cervical_spine", "lumbar_spine"):
            return "CR_AP_Lateral"
        if body_site in ("ankle", "foot"):
            return "CR_AP_Lateral_Oblique"
        if body_site == "wrist":
            return "CR_PA_Lateral_Oblique" if len(views) >= 3 else "CR_PA_Lateral"
    # CT — contrast is the discriminator; non-contrast is the default
    if modality == "CT":
        if body_site in ("chest", "abdomen", "abdomen_pelvis"):
            return "CT_contrast" if contrast else "CT_non_contrast"
        if body_site == "head":
            if "angiography" in views:  # Issue #2699: CT angiography of head and neck
                return "CTA"
            return "CT_non_contrast" if not contrast else "CT"
        if body_site in ("hip", "spine"):
            return "CT_non_contrast"
    # MR — non-contrast is the standard variant (contrast MR reserved for future)
    if modality == "MR":
        if body_site == "head" and "angiography" in views:  # Issue #2699: MR angiography
            return "MRA"
        if body_site in ("head", "spine", "biliary_tract", "lumbar_spine"):
            return "MR_non_contrast"
    # US — single procedure per body site (doppler for leg, generic for the rest)
    if modality == "US":
        if body_site == "leg":
            return "US_Doppler"
        if body_site in ("abdomen", "kidney", "skin", "heart", "carotid_artery", "urinary_bladder"):
            return "US"
    # ECG — a 12-lead electrocardiogram (Issue #2621); the waveform is
    # filed against the chest.
    if modality == "ECG" and body_site == "chest":
        return "ECG"
    # XA — coronary angiography is always a contrast study (Issue #2655)
    if modality == "XA" and body_site == "coronary_artery":
        return "XA_contrast"
    # MG — a bilateral screening mammogram (Issue #2870)
    if modality == "MG" and body_site == "breast":
        return "MG_screening"
    raise ValueError(
        f"Unsupported imaging combination: modality={modality} body_site={body_site} views={views} contrast={contrast}"
    )


def imaging_laterality(encounter_id: str, body_site: str) -> str:
    """The side ("left" / "right") a study of a paired structure images, or ""
    (Issue #2657). The orders carry no side, so one side is drawn per stay from
    a hash of the encounter (no RNG): every paired study of a stay images the
    same side."""
    if not (load_body_sites().get(body_site) or {}).get("paired"):
        return ""
    import hashlib

    digest = hashlib.sha256(f"clinosim:imaging-side:v1|{encounter_id}".encode()).digest()
    return "left" if digest[0] % 2 == 0 else "right"


def imaging_procedure_loinc(modality: str, body_site: str, views: list[str], contrast: bool) -> str:
    """The procedure LOINC of a study, or "" when the combination has none
    (Issue #2699: shared by the ServiceRequest, ImagingStudy and report)."""
    try:
        key = _resolve_imaging_procedure_code_key(modality, body_site, list(views or []), contrast)
        return str(load_body_sites()[body_site]["procedure_codes"][key]["loinc"])
    except (KeyError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# Canonical ID prefixes (writer-owned; Task 5 FHIR builders import from here).
# Shared constant pattern = silent-no-op defense Layer 2 (writer↔reader).
# ---------------------------------------------------------------------------
IMAGING_STUDY_ID_PREFIX = "imgst-"
ENDPOINT_ID_PREFIX = "endpoint-"
RADIOLOGY_REPORT_ID_PREFIX = "imgrpt-"


# ---------------------------------------------------------------------------
# Issue #918: series-as-studies consolidation (same physical scan window).
#
# Multiple imaging Orders on the same encounter for the same (modality,
# body_site) that fire within ``_SERIES_AS_STUDIES_WINDOW_MIN`` minutes of
# each other represent a single physical scan whose series were fanned
# out into separate Orders by overlapping specs (disease protocol +
# admission block + ED workup). FHIR ``ImagingStudy`` = one DICOM Study
# = one physical scan session, so we consolidate at enricher time by
# skipping the duplicates (same shape as the Issue #822 near-identical
# dedup, extended to catch same-(modality, body_site) within a wider
# window). The gap between adjacent "real" repeat imaging (e.g. control
# CT after intervention) is always ≥ 6h — the audit's 1-6h bucket has
# zero pairs — so a 60-minute window catches the series-as-studies
# fingerprint without touching any legitimate repeat.
#
# Only modalities that emit one FHIR study per physical acquisition are
# consolidated. Plain radiography (``CR``) legitimately repeats within
# a shift on ICU / pneumonia patients (daily portable film) and is left
# unconsolidated by design.
_SERIES_AS_STUDIES_WINDOW_MIN: int = 60
_CONSOLIDATABLE_MODALITIES: frozenset[str] = frozenset({"CT", "MR", "US", "XA"})


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
    # Issue #2654: a site may read with another site's templates
    # (abdomen + pelvis uses the abdomen reports).
    template_site = (load_body_sites().get(body_site_key) or {}).get("report_template_site") or body_site_key
    key = f"{modality}_{template_site}"
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
#: Text lives in narrative_phrases.yaml (imaging_report.generic_negative_*).


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
        findings_text=t("imaging_report.generic_negative_findings", "en"),
        findings_text_ja=t("imaging_report.generic_negative_findings", "ja"),
        impression_text=t("imaging_report.generic_negative_impression", "en"),
        impression_text_ja=t("imaging_report.generic_negative_impression", "ja"),
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
            # Issue #2796: a bedside eye examination is not an imaging study.
            and (_o(o, "display_name", "") or "") not in bedside_examination_names()
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
            rng = determinism.default_rng(sub_seed)

            modality: str = _o(order, "imaging_modality", "") or ""
            body_site_snomed: str = _o(order, "imaging_body_site_code", "") or ""
            views: list[str] = list(_o(order, "imaging_views", []) or [])
            # Case-D fix: infer metadata from ``display_name`` when the
            # order lacks it. On failure, emit a minimal ImagingStudy
            # with ``stub_only=True`` (see below).
            stub_only = False
            inferred: dict | None = None
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
            _order_encounter_id = _o(order, "encounter_id", "") or ""
            _dup = any(
                prev.encounter_id == _order_encounter_id
                and prev.started_datetime == _stub_started
                and _canonicalize_display(prev.description) == _canon
                for prev in studies
            )
            if _dup:
                continue

            # Issue #918: series-as-studies consolidation. Skip when a
            # prior study on the same encounter already covers this
            # (modality, body_site) within the ``_SERIES_AS_STUDIES_WINDOW_MIN``
            # window — these represent the same physical scan whose series
            # were fanned out into separate Orders by overlapping protocol
            # sources. Gated to CT/MR/US/XA — plain radiography (CR) is
            # left alone because same-shift chest-X-ray repeats on ICU /
            # pneumonia patients are clinically legitimate.
            if modality in _CONSOLIDATABLE_MODALITIES and body_site_snomed and _stub_started:
                _series_dup = any(
                    prev.encounter_id == _order_encounter_id
                    and prev.modality_code == modality
                    and prev.body_site_snomed == body_site_snomed
                    and prev.started_datetime is not None
                    and abs((_stub_started - prev.started_datetime).total_seconds()) / 60.0
                    <= _SERIES_AS_STUDIES_WINDOW_MIN
                    for prev in studies
                )
                if _series_dup:
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
                if stub_study.report is not None:
                    stub_study.report.issued_datetime = report_issued_datetime(
                        _stub_started, "", stub_study.patient_id, order_id
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
            # Issue #2654: an order without a structured spec (free-text
            # workup entry) takes the contrast from its name.
            contrast: bool = bool(
                spec_meta["contrast"] if "contrast" in spec_meta else (inferred or {}).get("contrast", False)
            )

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
                    # The CIF record's English and Japanese slots, from the
                    # template's language maps (Issue #2505).
                    findings_text=localized(template["findings"], "en"),
                    findings_text_ja=localized(template["findings"], "ja"),
                    impression_text=localized(template["impression"], "en"),
                    impression_text_ja=localized(template["impression"], "ja"),
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
                views=list(views),
                laterality=imaging_laterality(encounter_id, body_site_key),
                report=report,
                description=_non_stub_display,
            )
            report.issued_datetime = report_issued_datetime(
                study.started_datetime, modality, study.patient_id, order_id
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
