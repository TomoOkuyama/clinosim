"""Per-bundle build context shared by the FHIR bundle builders (Issue #2530)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "BundleContext",
]


@dataclass
class BundleContext:
    """Shared inputs for FHIR resource builders (AD-56)."""

    record: dict
    country: str
    roster_map: dict
    hospital_config: dict
    patient_data: dict
    patient_id: str
    is_readmission: bool
    prior_encounter_id: Any
    primary_dx_code: str
    admit_dx_code: str
    admit_dx_system: str
    primary_enc_id: str
    patient_sex: str
    # Issue #925: populated by `_build_bundle` right before the Composition
    # builders run — index of already-emitted resources bucketed by encounter
    # id and resourceType. Consumers (`_bb_compositions` +
    # `_bb_imaging_report_compositions`) use it to populate
    # `Composition.section[].entry[]` with references to the encounter's
    # MedicationRequests / Observations / Procedures / Conditions / ServiceRequests
    # / DiagnosticReports. Shape:
    #   {encounter_id: {resourceType: [{"reference": "…/id", "display": "…"?}, …]}}
    # `None` when the caller has not run the pre-composition indexing pass
    # (unit-tests exercising a single builder in isolation).
    encounter_resource_index: dict[str, dict[str, list[dict[str, str]]]] | None = None
    # Issue #944: simulation snapshot date (YYYY-MM-DD) from cif/metadata.json,
    # read once by `convert_cif_to_fhir` and threaded through so
    # `_build_coverage_resources` can decide Coverage.status per FY row
    # (active vs cancelled). None when the CIF has no metadata.json
    # (identity-only tests, non-standard callers) — builders MUST fall
    # back to their pre-#944 defaults in that case.
    snapshot_date: str | None = None
    # Issue #1217 (2026-09-10, JP p=10000 audit): the set of
    # MedicationRequest.id values actually emitted for this bundle after
    # ``_dedup_medication_requests`` (byte-identical, Issue #1177) and
    # ``_dedup_same_class_orders`` (same-class same-day, Issues #1176 /
    # #1179) drop duplicates. ``_build_bundle`` populates this from the
    # entries accumulated by earlier builders, right before
    # ``_bb_medication_admins`` runs. The MA builder consumes it to gate
    # ``MedicationAdministration.request.reference`` — references pointing
    # at MRs that were dropped by dedup are popped instead of dangling.
    # Concrete failure this gate guards: 357 dangling MA→MR references in
    # p=10k (insulin sliding-scale / enoxaparin standing-order /
    # prednisolone course, where MA is emitted per-day but MR dedup
    # coalesces the underlying orders into one MR).
    # ``None`` when the caller has not run the pre-MA index pass (unit
    # tests exercising a single builder in isolation) — the MA builder
    # falls back to the pre-#1217 order-set gate, matching the pre-fix
    # baseline for backwards compatibility.
    emitted_mr_ids: set[str] | None = None
