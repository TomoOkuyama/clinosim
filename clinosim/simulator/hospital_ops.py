"""Hospital-operations helpers — ward selection, department resolution.

Extracted from ``simulator/helpers.py`` (Issue #544). Consumes
``hospital_ops`` dict loaded from ``config/hospital_operations.yaml``.
Callers historically imported these names from ``simulator/helpers``;
those imports keep working via the helpers.py re-export facade.
"""

from __future__ import annotations

from typing import Any


def resolve_department(
    granular_dept: str,
    hospital_ops: dict | None,
) -> str:
    """Resolve a granular specialty to an available department at this hospital.

    Uses ``hospital_ops.department_rollup`` to map specialties (e.g.,
    pulmonology) to one of ``hospital_ops.available_departments`` (e.g.,
    internal_medicine). Falls back to ``internal_medicine`` if neither matches.
    """
    if not hospital_ops:
        return granular_dept or "internal_medicine"

    available = set(hospital_ops.get("available_departments", []))
    rollup = hospital_ops.get("department_rollup", {}) or {}

    if granular_dept in available:
        return granular_dept

    rolled = rollup.get(granular_dept)
    if rolled and rolled in available:
        return rolled

    if "internal_medicine" in available:
        return "internal_medicine"
    if available:
        return next(iter(available))
    return granular_dept or "internal_medicine"


def pick_ward(department: str, hospital_ops: dict | None, rng: Any) -> str:
    """Pick a ``ward_id`` for the given department from hospital config."""
    if hospital_ops:
        wards_map = hospital_ops.get("wards", {}) or {}
        options = wards_map.get(department, [])
        if options:
            return str(rng.choice(options)) if len(options) > 1 else options[0]
    return "4E"


_REQUIRED_KEYS = ("available_departments", "department_rollup", "wards", "ward_capacity", "resource_capacity")


def _is_outpatient_area(ward: str) -> bool:
    return ward in ("ER", "OPD") or ward.startswith("OPD-")


def validate_hospital_ops(hospital_ops: dict[str, Any], source: str) -> None:
    """Fail loudly on an incomplete or inconsistent hospital config (Issue #2128).

    A config missing ``wards`` / ``available_departments`` used to fall back
    silently to a hard-coded ward ("4E") and an internal-medicine-only roster.
    Checks: required keys; every ward department is an available department;
    every inpatient ward has a capacity and every capacity a ward; capacities
    sum to ``resource_capacity.inpatient_beds``; rollup targets are available.
    """
    missing = [k for k in _REQUIRED_KEYS if not hospital_ops.get(k)]
    if missing:
        raise ValueError(f"hospital config {source}: missing {missing}")
    available = set(hospital_ops["available_departments"])
    wards: dict[str, list[str]] = hospital_ops["wards"]
    capacity: dict[str, int] = hospital_ops["ward_capacity"]
    unknown_depts = sorted(set(wards) - available)
    if unknown_depts:
        raise ValueError(f"hospital config {source}: wards for unavailable departments {unknown_depts}")
    inpatient_wards = {w for ws in wards.values() for w in ws if not _is_outpatient_area(w)}
    if inpatient_wards != set(capacity):
        raise ValueError(
            f"hospital config {source}: wards without capacity {sorted(inpatient_wards - set(capacity))}, "
            f"capacity without ward {sorted(set(capacity) - inpatient_wards)}"
        )
    beds = int(hospital_ops["resource_capacity"].get("inpatient_beds", 0))
    if sum(capacity.values()) != beds:
        raise ValueError(f"hospital config {source}: ward capacities sum to {sum(capacity.values())}, not {beds} beds")
    bad_rollup = sorted(k for k, v in hospital_ops["department_rollup"].items() if v not in available)
    if bad_rollup:
        raise ValueError(f"hospital config {source}: rollup to unavailable departments for {bad_rollup}")
