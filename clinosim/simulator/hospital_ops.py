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
