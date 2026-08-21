"""Imaging CIF dataclasses (Tier 1 #2 PR1).

ImagingStudyRecord lives in record.extensions["imaging"] (AD-55 Module pattern,
device/hai/antibiotic precedent). FHIR ImagingStudy + Endpoint + radiology
DiagnosticReport are emitted from this CIF structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ImagingSeries:
    """One DICOM Series under an ImagingStudy.

    PR1 scope: CXR (1 series per view, 1 instance per series) and CT (1 series
    per body site, ~200-280 axial instances). Multi-view CXR (PA + Lateral) =
    2 series under the same Study.
    """

    series_uid: str = ""  # DICOM Series UID (integration point for a real PACS later).
    series_number: int = 1
    modality_code: str = ""  # DCM modality(CR/CT/MR/US/NM...)
    body_site_snomed: str = ""
    description: str = ""  # e.g. "PA view" / "axial 5mm".
    instance_count: int = 0  # Number of DICOM instances (placeholder).


@dataclass
class RadiologyReport:
    """Radiology DiagnosticReport content (template-driven; LLM integration point).

    findings_text + impression_text both populated from impression_templates.yaml.
    findings_codes is a forward-compat slot (PR1 leaves empty; future NLP/IE
    enrichment populates SNOMED finding codes → DR.conclusionCode emission gate
    auto-activates).
    """

    report_id: str = ""  # "imgrpt-{enc}-{n}"
    status: str = "final"  # FHIR registered/preliminary/final/amended
    findings_text: str = ""  # Structured findings narrative (English).
    findings_text_ja: str = ""  # ja copy for JP cohort (Task 6 FHIR builder picks by lang)
    impression_text: str = ""  # clinical impression / conclusion (en)
    impression_text_ja: str = ""  # ja copy for JP cohort (Task 6 FHIR builder picks by lang)
    findings_codes: list[str] = field(default_factory=list)  # Optional SNOMED finding codes.


@dataclass
class ImagingStudyRecord:
    """One imaging study event, one-to-one with an Order(OrderType.IMAGING).

    ``body_site_snomed`` at study level is denormalized for query convenience
    (= ``series[0].body_site_snomed`` for single-body-site Studies). FHIR emission
    goes via Series only (R4 ImagingStudy has no top-level bodySite field).
    """

    study_id: str = ""  # "imgst-{enc}-{n}"
    study_instance_uid: str = ""  # DICOM Study UID (lookup key for a real PACS later).
    encounter_id: str = ""
    patient_id: str = ""
    order_id: str = ""  # Source Order.order_id (resolves `basedOn`).

    status: str = "available"  # FHIR ImagingStudy.status
    started_datetime: datetime | None = None

    modality_code: str = ""  # DCM modality
    body_site_snomed: str = ""
    series: list[ImagingSeries] = field(default_factory=list)

    endpoint_id: str = ""  # back-ref to Endpoint.id(1 study : 1 Endpoint)

    contrast: bool = False  # True = contrast-enhanced CT (propagated from Order.imaging_spec_meta)
    report: RadiologyReport | None = None  # snapshot mid-study = None
    # Issue #822 (N-9): Order-level display for stub-only studies (where the
    # normal metadata-inference path fails so `_proc_display` is not
    # resolvable). Populated in the enricher's stub-only branch from
    # order.display_name; FHIR emit uses it as the informative
    # `ImagingStudy.description` fallback instead of an empty field.
    description: str = ""
