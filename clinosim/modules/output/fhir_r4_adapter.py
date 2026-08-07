"""FHIR R4 adapter — Stage 3: convert CIF structural data to FHIR R4 Bundles.

Generates one FHIR Bundle (JSON) per patient containing:
  Patient, Encounter, Observation (labs + vitals), MedicationRequest, Practitioner references.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from clinosim.modules._shared import is_jp
from clinosim.modules.output._fhir_allergy_intolerance import _bb_allergy_intolerances
from clinosim.modules.output._fhir_care_level import _bb_care_level
from clinosim.modules.output._fhir_care_team import _bb_care_teams
from clinosim.modules.output._fhir_clinical_impression import _bb_clinical_impressions
from clinosim.modules.output._fhir_code_status import _bb_code_status

# FA-1 (Phases 1-13) + session 82 (H/I/K/L/N) split this adapter's leaf data,
# shared fragment helpers, and per-theme resource builders into sibling
# `_fhir_*` modules. The imports below are exactly the symbols `_build_bundle`
# and `convert_cif_to_fhir` (this module's public surface) actually call —
# the historical facade re-export block (marked with `noqa` directives) was
# dropped once tests migrated to canonical imports.
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _entry,
)
from clinosim.modules.output._fhir_composition import _bb_compositions
from clinosim.modules.output._fhir_device import (
    _bb_device,
    _bb_device_use,
)
from clinosim.modules.output._fhir_diagnostic_report import _bb_diagnostic_reports
from clinosim.modules.output._fhir_document_reference_checkup import _bb_document_references_checkup
from clinosim.modules.output._fhir_documents import _bb_document_references
from clinosim.modules.output._fhir_endpoint import _bb_endpoints
from clinosim.modules.output._fhir_facility import _build_facility_bundle
from clinosim.modules.output._fhir_family_history import _bb_family_history
from clinosim.modules.output._fhir_generator_metadata import write_generator_metadata as _write_generator_metadata
from clinosim.modules.output._fhir_hai import _bb_hai_conditions
from clinosim.modules.output._fhir_imaging_study import _bb_imaging_studies
from clinosim.modules.output._fhir_immunization import _bb_immunizations
from clinosim.modules.output._fhir_inline_bb import (
    _bb_conditions,
    _bb_coverage,
    _bb_discharge_medication_requests,
    _bb_encounters,
    _bb_medication_admins,
    _bb_medication_requests,
    _bb_occupation,
    _bb_patient,
    _bb_practitioners,
    _bb_procedures,
    _bb_vitals,
)
from clinosim.modules.output._fhir_microbiology import _bb_microbiology
from clinosim.modules.output._fhir_nursing import _bb_nursing_observations
from clinosim.modules.output._fhir_observations import _bb_labs

# Session 82 PR N: post-emit helpers extracted to _fhir_post_process.py.
# Imported for use inside `_build_bundle` (see finalize pass).
from clinosim.modules.output._fhir_post_process import (
    _apply_jp_clins_profile,
    _apply_jp_core_profile,
    _build_companion_specimen,
    _lab_observation_needs_specimen,
    _normalize_dt_fields,
    _normalize_jp_observation_category,
    _populate_condition_ai_mr_ecs_fields,
    _populate_jp_medication_dosage_ecs_fields,
    _populate_observation_identifier_and_last_updated,
    _strip_forbidden_observation_reference_range_extensions,
    _strip_japanese_display_on_english_only_systems,
)
from clinosim.modules.output._fhir_service_request import _bb_service_requests
from clinosim.modules.output._fhir_smoking_alcohol import (
    _bb_alcohol_use,
    _bb_smoking_status,
)
from clinosim.modules.output.cif_reader import CIFReader
from clinosim.simulator import log as sim_log

# FHIR R4 `Resource.id` type: `[A-Za-z0-9\-\.]{1,64}`. iris4h-ai P0 finding
# (2026-07-17): 812,606 ids across the export violated this spec — `_` in id
# and >64 char ids were rejected by IRIS FHIR endpoint with HTTP 400. HAPI
# validator is more lenient but the FHIR spec is strict. The regex here is the
# single source of truth for the pattern — every writer path routes ids
# through it, and any non-conforming id logs a warning (fail-soft: the write
# still succeeds so a bug in a single builder does not break the whole export,
# but the log lets the audit CI catch regressions).
_FHIR_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-\.]{1,64}$")


def _fhir_id_is_spec_valid(rid: str) -> bool:
    """True if ``rid`` conforms to FHIR R4 `Resource.id` = `[A-Za-z0-9\\-\\.]{1,64}`."""
    return bool(_FHIR_ID_PATTERN.match(rid))


def convert_cif_to_fhir(
    cif_dir: str,
    output_dir: str,
    country: str = "US",
    narrative_version: str = "current",
) -> None:
    """Read CIF structural data and write FHIR R4 Bulk Data Export NDJSON files.

    Output follows the HL7 FHIR Bulk Data Access spec:
    one NDJSON file per resource type (Patient.ndjson, Encounter.ndjson, etc.).
    Each line is a single FHIR resource (no Bundle wrapping).

    DocumentReference / Composition resources are emitted from
    record.documents, merged with narrative content by CIFReader (AD-65 Task
    4): structural stubs are created by document_enricher at POST_ENCOUNTER
    (Task 8); narrative text/sections are populated by a separate Stage 2
    NarrativePass (Task 3) and merged in at read time here.

    Args:
        cif_dir: path to a cif/ directory containing structural/.
        output_dir: directory to write the FHIR NDJSON files.
        country: "US" or "JP" — selects display language and code systems.
        narrative_version: narrative layer to merge in — "current" (default,
            resolved via cif/narratives/current_version.txt, falling back to
            "template") or an explicit version_id.
    """
    os.makedirs(output_dir, exist_ok=True)

    reader = CIFReader(cif_dir, narrative_version=narrative_version)

    # Load hospital data (Practitioner roster + Organization/Location config)
    roster_map: dict[str, dict] = {}
    hospital_config: dict = {}
    hospital_path = os.path.join(cif_dir, "hospital.json")
    if os.path.exists(hospital_path):
        with open(hospital_path) as f:
            hospital_data = json.load(f)
        for staff in hospital_data.get("staff", []):
            roster_map[staff.get("staff_id", "")] = staff
        hospital_config = hospital_data.get("config", {}) or {}

    # Open NDJSON file handles for each resource type
    # Use a writer cache to lazy-create files only for types we encounter
    writers: dict[str, Any] = {}
    written_ids: dict[str, set[str]] = {}  # de-dup Patient and Practitioner
    invalid_id_counts: dict[str, int] = {}  # per-resource-type spec-violation tally

    def write(resource: dict) -> None:
        rt = resource.get("resourceType", "")
        if not rt:
            return
        # Enforce global Resource.id uniqueness within each type (FHIR requirement).
        # Patient-level resources (Patient, AllergyIntolerance, Coverage, occupation
        # Observation, ...) recur across a patient's per-encounter bundles; keep the
        # first write only. Per-encounter resources have unique ids → never dropped.
        rid = resource.get("id", "")
        # FHIR R4 `Resource.id` spec check (iris4h-ai P0 finding, 2026-07-17).
        # Fail-soft: increment the per-type counter and log a warning at
        # export end. The write itself proceeds — a spec-invalid id from a
        # regressed builder should surface loudly but not break the whole
        # export.
        if rid and not _fhir_id_is_spec_valid(rid):
            invalid_id_counts[rt] = invalid_id_counts.get(rt, 0) + 1
        if rid:
            ids = written_ids.setdefault(rt, set())
            if rid in ids:
                return
            ids.add(rid)
        if rt not in writers:
            path = os.path.join(output_dir, f"{rt}.ndjson")
            writers[rt] = open(path, "w", encoding="utf-8")
        writers[rt].write(json.dumps(resource, ensure_ascii=False) + "\n")

    # Issue #175: bracket the whole export with `sim_log` so `tail -f
    # simulator.log` sees a clear ``fhir_export_start`` / ``fhir_export_end``
    # boundary with elapsed_s + resources count for the p=10000 blind
    # window that used to sit between ``run_beta_done`` and manifest write.
    import time as _time

    t0_export = _time.perf_counter()
    sim_log.info(
        "fhir_r4_adapter",
        "fhir_export_start",
        country=country,
        output_dir=output_dir,
        narrative_version=narrative_version,
    )
    n_resources = 0
    n_patients = 0
    try:
        # Master resources (Organization + Location + Device) — written once.
        # Facility resources bypass `_build_bundle`, so the JP-only post-emit
        # walkers must be reapplied here or they leak untouched Japanese
        # display / raw HL7 URIs into the facility subset (iris4h-ai
        # feedback V4/V5 P2 A regression when Device / Location emit HL7
        # / SNOMED / DICOM coding with Japanese display).
        facility_bundle = _build_facility_bundle(hospital_config, country)
        for entry in facility_bundle.get("entry", []):
            resource = entry["resource"]
            if is_jp(country):
                _apply_jp_core_profile(resource)
                _apply_jp_clins_profile(resource)
                _normalize_jp_observation_category(resource)
                _strip_japanese_display_on_english_only_systems(resource)
                # PR-I (2026-07-17): populate JP-CLINS MedicationDosage_eCS
                # required fields (extension:periodOfUse + timing.code with the
                # uncoded dummy usage code that satisfies R5020). No-op on the
                # facility bundle since it emits no MedicationRequests.
                _populate_jp_medication_dosage_ecs_fields(resource)
            # Runs regardless of country: identifier / meta.lastUpdated are
            # base-FHIR-optional but JP-eCS-required; universal emission keeps
            # US output consistent and cost-free.
            _populate_observation_identifier_and_last_updated(resource, country)
            # #202 (2026-07-17): scrub `Observation.referenceRange[*].extension`
            # (and low/high/component mirrors). LabResult_eCS forbids them
            # (max=0) and the previously-emitted `referenceRangeSource` URL
            # was not registered anywhere in JP-CLINS 1.12.0. Universal —
            # US output already omits the extension so the walker is a no-op.
            _strip_forbidden_observation_reference_range_extensions(resource)
            # PR-E (2026-07-17): emit companion Specimen for lab Observations
            # (JP_Observation_LabResult_eCS.specimen min=1). No-op on the
            # facility bundle (no lab Observations) but keeps the code path
            # symmetric with the main bundle loop.
            if _lab_observation_needs_specimen(resource):
                specimen = _build_companion_specimen(resource, country)
                resource["specimen"] = {"reference": f"Specimen/{specimen['id']}"}
                if is_jp(country):
                    # Same JP-only walkers as any other resource: SNOMED
                    # `display` on the Specimen.type coding is English-only,
                    # so the P2 A walker strips Japanese chars — the JP text
                    # stays in `type.text` per feedback Option 1.
                    _strip_japanese_display_on_english_only_systems(specimen)
                _normalize_dt_fields(specimen, country)
                write(specimen)
                n_resources += 1
            # PR-G (2026-07-17): populate JP-CLINS eCS-required fields on
            # Condition / AllergyIntolerance / MedicationRequest. Universal —
            # US output picks up the same fields harmlessly.
            _populate_condition_ai_mr_ecs_fields(resource, country)
            _normalize_dt_fields(resource, country)
            write(resource)
            n_resources += 1

        # Walk patient records (structural + merged narrative), build per-record
        # FHIR resources, write each line. Patient-scoped resources
        # (chronic problem-list-item Condition, Coverage, AllergyIntolerance,
        # FamilyMemberHistory, Immunization) use patient-scoped IDs so the
        # `write()` helper's `written_ids` dedup keeps them at one per patient
        # (root-cause fix for cycle 3 RM-7 problem-list-item excess = per-
        # encounter re-emission with encounter-scoped IDs, C4-02 session 43).
        for record in reader.iter_patients():
            n_patients += 1
            bundle = _build_bundle(record, country, roster_map, hospital_config)
            for entry in bundle.get("entry", []):
                write(entry["resource"])
                n_resources += 1

        # Manifest (FHIR Bulk Data spec)
        manifest = {
            "transactionTime": datetime.now().isoformat(),
            "request": f"clinosim generate (country={country})",
            "requiresAccessToken": False,
            "output": [{"type": rt, "url": f"{rt}.ndjson"} for rt in sorted(writers.keys())],
            "error": [],
        }
        with open(os.path.join(output_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        # Sidecar `_generator_metadata.json` (issue #206): validators and
        # downstream ingestion pipelines want to know which clinosim revision
        # generated a given export so they can correlate observed validation
        # results with the fix-PRs already applied. The leading underscore
        # keeps the file out of the FHIR resource-type namespace, so tools
        # iterating `manifest.json.output[*]` never see it as a resource file.
        # Soft-failure: any error is logged and swallowed inside
        # `write_generator_metadata` — the export loop continues.
        _write_generator_metadata(output_dir, cif_dir, country)
    finally:
        # F2 (session 49): close writers, then rewrite each NDJSON file with
        # its resources sorted by id ascending. Row order is otherwise
        # cursor-dependent (patient_records iteration order), so a line diff
        # between two snapshots (cursor A / cursor B) would surface spurious
        # "line moved" noise. Sorting by id makes the diff reflect only
        # genuine new / changed / removed resources.
        for w in writers.values():
            w.close()
        # The sort pass is O(seconds) per NDJSON file on p=10000 — bracket
        # it separately so profile tooling can attribute the fraction of
        # export wall-clock spent here vs the per-resource write loop.
        t0_sort = _time.perf_counter()
        sim_log.info(
            "fhir_r4_adapter",
            "ndjson_sort_start",
            files=len(writers),
        )
        for rt in writers:
            path = os.path.join(output_dir, f"{rt}.ndjson")
            _sort_ndjson_by_id_inplace(path)
        sim_log.info(
            "fhir_r4_adapter",
            "ndjson_sort_end",
            files=len(writers),
            elapsed_s=round(_time.perf_counter() - t0_sort, 3),
        )
    # Surface FHIR-id spec violations tallied inside `write()`. Empty when
    # every emitted id conforms to `[A-Za-z0-9\-\.]{1,64}`; a non-empty dict
    # indicates a regressed builder and shows up in `simulator.log` for the
    # audit CI to flag (iris4h-ai P0 finding, 2026-07-17).
    if invalid_id_counts:
        sim_log.info(
            "fhir_r4_adapter",
            "invalid_fhir_ids",
            counts=dict(invalid_id_counts),
            total=sum(invalid_id_counts.values()),
        )
    sim_log.info(
        "fhir_r4_adapter",
        "fhir_export_end",
        country=country,
        patients=n_patients,
        resources=n_resources,
        files=len(writers),
        elapsed_s=round(_time.perf_counter() - t0_export, 3),
    )


def _sort_ndjson_by_id_inplace(path: str) -> None:
    """Rewrite an NDJSON file in place with lines sorted by resource id ascending.

    F2 (session 49): sorting removes cursor-dependent (patient_records
    iteration order) row ordering so that a line diff between two snapshots
    surfaces only genuine new / changed / removed resources, not spurious
    "line moved" noise.

    Reads the whole file into memory, so RAM usage scales with file size —
    at p=10k total NDJSON output is ~4.7GB, with the largest single file
    (Observation.ndjson) in the multi-GB range. This is acceptable for
    Phase A; a future JP p=500k scale may need to replace this with an
    external merge sort, but in-memory sort is sufficient for now.
    """
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    lines.sort(key=lambda line: json.loads(line).get("id", ""))
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


# --- Resource builders: (ctx) -> list[resource]. Order here == emission order. ---


# Registry: emission order == list order. New Base/Module resources append a builder
# here (or via register_bundle_builder) instead of editing _build_bundle (AD-56).
_BUNDLE_BUILDERS: list[Callable[[BundleContext], list[dict]]] = [
    _bb_patient,
    _bb_coverage,
    _bb_encounters,
    _bb_care_teams,  # α-min-2 Task 11: 1 CareTeam per encounter (attending + nurse)
    _bb_conditions,
    _bb_allergy_intolerances,  # Task 9 / Task 15: 8-field SNOMED-coded schema (sole emit path)
    _bb_clinical_impressions,  # Task 9: ClinicalImpression (daily working diagnosis)
    _bb_occupation,
    _bb_service_requests,
    _bb_endpoints,  # Imaging: emit after SR, before ImagingStudy (reference resolve order)
    _bb_imaging_studies,  # Imaging: emit after Endpoint (endpoint[] ref resolve)
    _bb_labs,
    _bb_vitals,
    _bb_microbiology,
    _bb_diagnostic_reports,
    _bb_medication_requests,
    _bb_discharge_medication_requests,  # Issue #445: discharge / outpatient-renewal prescriptions
    _bb_medication_admins,
    _bb_procedures,
    _bb_practitioners,
    _bb_nursing_observations,
    _bb_immunizations,
    _bb_family_history,
    _bb_code_status,
    _bb_smoking_status,
    _bb_alcohol_use,
    _bb_care_level,
    _bb_device,
    _bb_device_use,
    _bb_hai_conditions,
    _bb_document_references,  # Task 10: DocumentReference from record.documents (free_text, §2.2)
    _bb_compositions,  # Task 9: Composition (section-structured H&P / Discharge)
    _bb_document_references_checkup,  # P2-13 PR3 sub-PR-E (session 48): DocumentReference wrapper for HEALTH_CHECKUP_REPORT  # noqa: E501
]


# Import-time contract (Issue #558): every registry entry MUST use the `_bb_`
# prefix. `_build_X` is reserved for single-resource helpers (returning a
# `dict`); `_bb_X` marks a bundle-builder (returning `list[dict]`). Mixing the
# two on this list would silently break grep-by-role and let a stray
# single-resource builder slip in without a type error. See
# `modules/output/README.md` for the full convention.
assert all(cb.__name__.startswith("_bb_") for cb in _BUNDLE_BUILDERS), (
    "Bundle builders must use the _bb_ prefix. Offenders: "
    f"{[cb.__name__ for cb in _BUNDLE_BUILDERS if not cb.__name__.startswith('_bb_')]}. "
    "See modules/output/README.md."
)


def register_bundle_builder(builder: Callable[[BundleContext], list[dict]]) -> None:
    """Register a FHIR resource builder appended after the built-ins (AD-56).

    Deduplicated by function name (first registration wins), so a second builder with
    the same name — e.g. a re-import of the same module — is not double-registered.

    Enforces the `_bb_` prefix contract (Issue #558) so external registrations
    honour the same convention as the built-in registry above.
    """
    if not builder.__name__.startswith("_bb_"):
        raise ValueError(f"Bundle builder {builder.__name__!r} must use the _bb_ prefix. See modules/output/README.md.")
    if builder.__name__ not in {b.__name__ for b in _BUNDLE_BUILDERS}:
        _BUNDLE_BUILDERS.append(builder)


def available_builders() -> list[str]:
    """Names of the registered bundle builders, in execution order (introspection)."""
    return [b.__name__ for b in _BUNDLE_BUILDERS]


def _build_bundle(
    record: dict,
    country: str,
    roster_map: dict[str, dict] | None = None,
    hospital_config: dict | None = None,
) -> dict:
    """Build a FHIR R4 Bundle from a CIF patient record by running the builder registry."""
    if roster_map is None:
        roster_map = {}
    if hospital_config is None:
        hospital_config = {}
    patient_data = record.get("patient", {})
    dx = record.get("clinical_diagnosis", {})
    encounters = record.get("encounters") or []
    # Session 45 seed=400 verification finding: record.deceased was set by
    # `_evaluate_mortality` in the inpatient simulator (74 expired IMP
    # encounters at seed=400 v2) but never propagated to `patient_data`, so
    # `_build_patient` always emitted `deceasedBoolean=False`. Copy the flag
    # + death timestamp into patient_data so the FHIR Patient carries a
    # `deceasedDateTime` matching the Encounter.dischargeDisposition="expired".
    _record_deceased = record.get("deceased", False) if isinstance(record, dict) else getattr(record, "deceased", False)
    if _record_deceased and not patient_data.get("date_of_death") and not patient_data.get("dod"):
        _dod = None
        for _enc in encounters:
            _dis = (
                _enc.get("discharge_datetime") if isinstance(_enc, dict) else getattr(_enc, "discharge_datetime", None)
            )
            if _dis:
                _dod = _dis
                break
        if _dod:
            patient_data = dict(patient_data)
            patient_data["date_of_death"] = str(_dod)
    ctx = BundleContext(
        record=record,
        country=country,
        roster_map=roster_map,
        hospital_config=hospital_config,
        patient_data=patient_data,
        patient_id=patient_data.get("patient_id", "unknown"),
        is_readmission=record.get("is_readmission", False),
        prior_encounter_id=record.get("prior_encounter_id"),
        primary_dx_code=dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", ""),
        admit_dx_code=dx.get("admission_diagnosis_code", ""),
        admit_dx_system=dx.get("admission_diagnosis_system", "icd-10-cm"),
        # CY7-05 (structural fix): CIFPatientRecord contract — primary
        # (IMP) encounter is always at encounters[0]; synthesized ED
        # encounter (when present) is appended at [1].
        primary_enc_id=encounters[0].get("encounter_id", "") if encounters else "",
        patient_sex=patient_data.get("sex", ""),
    )

    entries: list[dict] = []
    for builder in _BUNDLE_BUILDERS:
        for resource in builder(ctx):
            # C3-11..18 (session 42 cycle 3): apply JP Core profile URLs at
            # the adapter level so every resource type gains conformance
            # declarations without touching each builder. Coverage / Patient /
            # Encounter / Condition already carry inline profile; the helper is
            # idempotent (skips when meta.profile is already populated).
            if is_jp(ctx.country):
                _apply_jp_core_profile(resource)
                _apply_jp_clins_profile(resource)
                # JP Core は Observation.category:first slice に
                # JP_SimpleObservationCategory_CS を、HL7 base Vital Signs
                # profile(bp / heartrate / oxygensat / bodytemp / resprate)は
                # VSCat slice に HL7 category coding を要求する。両方を
                # 満たしつつ display 誤り error(V5 発見 A')も同時に解消
                # する single seam(builders 個別修正回避)。
                _normalize_jp_observation_category(resource)
                # iris4h-ai feedback V4/V5 P2 A: LOINC / SNOMED / HL7
                # terminology / DICOM / FHIR sid など英語 display のみ定義
                # されている「standard CodeSystem」に対し、clinosim が
                # 日本語 display を emit していると HAPI Validator が
                # 「Wrong Display Name」error を出す(~635k 件)。feedback
                # Option 1「display 省略、tx server が英語を補完」を採用し、
                # builders 個別修正の代わりに単一 walker で strip する。
                # CodeableConcept 側の text は保持されるため人間可読性は
                # (text 未設定な Coding-direct field を除いて)維持。
                _strip_japanese_display_on_english_only_systems(resource)
                # PR-I (2026-07-17): populate JP-CLINS MedicationDosage_eCS
                # required fields on MedicationRequest.dosageInstruction[].
                _populate_jp_medication_dosage_ecs_fields(resource)
            # PR-D (2026-07-17): populate Observation.identifier + meta.lastUpdated
            # (JP eCS min=1). Universal — safe on US output.
            _populate_observation_identifier_and_last_updated(resource, country)
            # #202 (2026-07-17): scrub `Observation.referenceRange[*].extension`
            # (and low/high/component mirrors). LabResult_eCS forbids them
            # (max=0) and the previously-emitted `referenceRangeSource` URL
            # was not registered anywhere in JP-CLINS 1.12.0. Universal —
            # US output already omits the extension so the walker is a no-op.
            _strip_forbidden_observation_reference_range_extensions(resource)
            # PR-E (2026-07-17): emit companion Specimen for lab Observations
            # (JP_Observation_LabResult_eCS.specimen min=1). The Specimen is
            # added to the bundle entries alongside the Observation, and the
            # Observation carries a `specimen` reference pointing at it.
            if _lab_observation_needs_specimen(resource):
                specimen = _build_companion_specimen(resource, country)
                resource["specimen"] = {"reference": f"Specimen/{specimen['id']}"}
                if is_jp(country):
                    _strip_japanese_display_on_english_only_systems(specimen)
                _normalize_dt_fields(specimen, country)
                entries.append(_entry(specimen))
            # PR-G (2026-07-17): populate JP-CLINS eCS-required fields on
            # Condition / AllergyIntolerance / MedicationRequest. Universal.
            _populate_condition_ai_mr_ecs_fields(resource, country)
            # session 48 feedback FB-F1: 全 emit resource の dateTime / instant
            # field を single seam で TZ 付与に正規化(builders 個別修正回避)。
            _normalize_dt_fields(resource, country)
            entries.append(_entry(resource))

    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "entry": entries,
    }


# ============================================================
# Resource builders
# ============================================================


# Clinical abbreviations / short names for common conditions.
# Keyed by ICD base code (before "."), with per-language short forms.
# coding[].display keeps the official ICD name; code.text uses these.


# JIS X 0401 prefecture codes

# US state abbreviation to FIPS code (common ones)


# SNOMED specialty codes
