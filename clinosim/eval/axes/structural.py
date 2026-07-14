"""Structural axis — FHIR compliance checks (5 checks, MVP)."""

from __future__ import annotations

from clinosim.audit.types import Cohort
from clinosim.eval.engine import EvalCheck, Outcome, Severity


def run(cohort: Cohort, country: str) -> list[EvalCheck]:
    return [
        _check_resource_id_uniqueness(cohort, country),
        _check_reference_integrity(cohort, country),
        _check_required_fields_present(cohort, country),
        _check_meta_profile_declared(cohort, country),
        _check_resource_type_consistency(cohort, country),
    ]


# --------------------------------------------------------------------------- #

def _check_resource_id_uniqueness(cohort: Cohort, country: str) -> EvalCheck:
    """Within each resourceType file, no two rows may share `id`."""
    dup_by_type: dict[str, int] = {}
    for path in _fhir_ndjsons(cohort, country):
        seen: set[str] = set()
        dupes = 0
        for row in _read_ndjson(path):
            rid = row.get("id")
            if not rid:
                continue
            if rid in seen:
                dupes += 1
            seen.add(rid)
        if dupes:
            dup_by_type[path.stem] = dupes

    if not dup_by_type:
        return EvalCheck(
            name="resource_id_uniqueness",
            outcome=Outcome.PASS,
            severity=Severity.CRITICAL,
            message="All resource ids are unique within their resourceType.",
        )
    return EvalCheck(
        name="resource_id_uniqueness",
        outcome=Outcome.FAIL,
        severity=Severity.CRITICAL,
        message=f"{sum(dup_by_type.values())} duplicate id(s) across {len(dup_by_type)} resourceType(s)",
        detail={"duplicates_by_type": dup_by_type},
    )


def _check_reference_integrity(cohort: Cohort, country: str) -> EvalCheck:
    """Every `reference` field must resolve to an emitted resource id."""
    # Collect the set of ResourceType/id declared by the cohort.
    declared: set[str] = set()
    references: list[str] = []
    for path in _fhir_ndjsons(cohort, country):
        rt = path.stem
        for row in _read_ndjson(path):
            rid = row.get("id")
            if rid:
                declared.add(f"{rt}/{rid}")
            references.extend(_walk_references(row))

    dangling = [r for r in references if r not in declared and _looks_like_internal_ref(r)]
    if not dangling:
        return EvalCheck(
            name="reference_integrity",
            outcome=Outcome.PASS,
            severity=Severity.CRITICAL,
            message=f"All {len(references)} internal reference(s) resolve.",
        )
    # Report up to 5 examples in the message; full list in `detail`.
    return EvalCheck(
        name="reference_integrity",
        outcome=Outcome.FAIL,
        severity=Severity.CRITICAL,
        message=(
            f"{len(dangling)} dangling reference(s) — examples: "
            + ", ".join(dangling[:5])
        ),
        detail={"dangling_sample": dangling[:20], "dangling_total": len(dangling)},
    )


def _check_required_fields_present(cohort: Cohort, country: str) -> EvalCheck:
    """Spot-check required-cardinality fields on the core resource types."""
    problems: list[str] = []

    # Patient.identifier: 0..* per spec but a synthetic EHR without it is
    # useless — clinosim always emits at least one. Missing = a real defect.
    for row in _read_ndjson_by_type(cohort, country, "Patient"):
        if not row.get("identifier"):
            problems.append(f"Patient/{row.get('id', '?')} missing identifier")

    # Encounter.status is required by FHIR R4 (1..1).
    for row in _read_ndjson_by_type(cohort, country, "Encounter"):
        if not row.get("status"):
            problems.append(f"Encounter/{row.get('id', '?')} missing status")

    # Condition.subject is required by FHIR R4 (1..1).
    for row in _read_ndjson_by_type(cohort, country, "Condition"):
        if not row.get("subject"):
            problems.append(f"Condition/{row.get('id', '?')} missing subject")

    if not problems:
        return EvalCheck(
            name="required_fields_present",
            outcome=Outcome.PASS,
            severity=Severity.MAJOR,
            message="Required cardinality fields present on Patient, Encounter, Condition.",
        )
    return EvalCheck(
        name="required_fields_present",
        outcome=Outcome.FAIL,
        severity=Severity.MAJOR,
        message=f"{len(problems)} required-field violation(s); examples: {problems[:3]}",
        detail={"problems_sample": problems[:20], "problems_total": len(problems)},
    )


def _check_meta_profile_declared(cohort: Cohort, country: str) -> EvalCheck:
    """For JP cohorts, every emitted primary resource type should carry
    ``meta.profile`` — the session-46 milestone was 16 primary types at 100%.
    For US, this check is N/A (no US Core profiles asserted yet)."""
    # Delegate country detection to the locale axis's helper (handles flat
    # cohorts where the directory doesn't encode the country).
    from clinosim.eval.axes.locale import _detect_country_from_cohort
    if _detect_country_from_cohort(cohort, country) != "JP":
        return EvalCheck(
            name="meta_profile_declared",
            outcome=Outcome.NA,
            severity=Severity.MAJOR,
            message="Non-JP cohort — no US Core / other locale profiles asserted; check N/A.",
        )

    expected_types = (
        "Patient", "Practitioner", "PractitionerRole", "Organization",
        "Location", "Encounter", "Condition", "Observation", "MedicationRequest",
        "MedicationAdministration", "DiagnosticReport", "Procedure",
        "AllergyIntolerance", "Immunization", "Coverage",
    )

    missing_profile: dict[str, int] = {}
    for rt in expected_types:
        without = 0
        total = 0
        for row in _read_ndjson_by_type(cohort, country, rt):
            total += 1
            profile = (row.get("meta") or {}).get("profile") or []
            if not profile:
                without += 1
        if total > 0 and without > 0:
            missing_profile[rt] = without

    if not missing_profile:
        return EvalCheck(
            name="meta_profile_declared",
            outcome=Outcome.PASS,
            severity=Severity.MAJOR,
            message=f"All {len(expected_types)} JP Core primary resource types declare meta.profile.",
        )
    return EvalCheck(
        name="meta_profile_declared",
        outcome=Outcome.WARN,
        severity=Severity.MAJOR,
        message=f"{len(missing_profile)} resource type(s) missing meta.profile — see detail",
        detail={"missing_profile_by_type": missing_profile},
    )


def _check_resource_type_consistency(cohort: Cohort, country: str) -> EvalCheck:
    """Every row in ``X.ndjson`` must have ``resourceType == "X"``."""
    problems: list[str] = []
    for path in _fhir_ndjsons(cohort, country):
        expected = path.stem
        for row in _read_ndjson(path):
            rt = row.get("resourceType")
            if rt != expected:
                problems.append(f"{path.name}: expected {expected!r}, got {rt!r}")
                if len(problems) > 20:
                    break
        if len(problems) > 20:
            break

    if not problems:
        return EvalCheck(
            name="resource_type_consistency",
            outcome=Outcome.PASS,
            severity=Severity.MINOR,
            message="Every NDJSON row's resourceType matches the filename.",
        )
    return EvalCheck(
        name="resource_type_consistency",
        outcome=Outcome.FAIL,
        severity=Severity.MINOR,
        message=f"{len(problems)} inconsistent resourceType/filename pair(s)",
        detail={"problems_sample": problems[:20]},
    )


# --------------------------------------------------------------------------- #
# helpers

def _fhir_ndjsons(cohort: Cohort, country: str):
    base = cohort.root / country / "fhir_r4"
    if not base.exists():
        return []
    return sorted(base.glob("*.ndjson"))


def _read_ndjson(path):
    import json
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _read_ndjson_by_type(cohort: Cohort, country: str, resource_type: str):
    path = cohort.root / country / "fhir_r4" / f"{resource_type}.ndjson"
    if not path.exists():
        return iter(())
    return _read_ndjson(path)


def _walk_references(obj, path: str = "") -> list[str]:
    """Return every string found under a `reference` key anywhere in the tree."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "reference" and isinstance(v, str):
                out.append(v)
            else:
                out.extend(_walk_references(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_walk_references(item))
    return out


def _looks_like_internal_ref(ref: str) -> bool:
    """`Patient/xyz`-style references we can validate. External URIs
    (`urn:oid:...`, `http://...`) are out of scope."""
    if not ref or ":" in ref:
        return False
    if "/" not in ref:
        return False
    resource_type, _ = ref.split("/", 1)
    return resource_type[:1].isupper() and resource_type.isalpha()
