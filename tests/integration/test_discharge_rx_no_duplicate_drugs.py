"""A' Phase 1 (Issue #440) invariant: discharge_prescription.items must not
contain the same drug name twice.

Rationale: with A' now syncing ``patient_cache[pid].current_medications``
across encounters, the two append paths in ``_build_discharge_rx``
(``protocol.drugs['discharge_oral']`` and the chronic-transcribe loop over
``patient.current_medications``) can each contribute the same drug name.
Without the exact-name dedup added in this PR, the drug accumulates on
every subsequent admission (2 admissions → 2 copies, 3 → 3, etc.). This
test is the durable guard against that regression.

Match key: whitespace-normalized lowercase ``drug_name``. Representational
variants (e.g. "Insulin glargine" vs "Insulin glargine 4 units/kg/day") are
intentionally NOT collapsed — dose/formulation differences are clinically
meaningful.
"""

from __future__ import annotations

from collections import Counter

import pytest

from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig


def _dedup_key(name: str) -> str:
    return " ".join(name.lower().split())


@pytest.mark.integration
def test_no_duplicate_drug_names_in_discharge_prescription():
    """Same cohort as the A' carryforward gate (POP-000002 is the fixture
    that would fail without dedup)."""
    config = SimulatorConfig(
        random_seed=123,
        catchment_population=600,
        country="US",
        time_range=("2025-01", "2026-01"),
    )
    ds = run_beta(config)

    offenders: list[tuple[str, str, dict[str, int]]] = []
    total_admissions = 0
    for r in ds.patients:
        if not r.encounters:
            continue
        if r.encounters[0].encounter_type.value != "inpatient":
            continue
        total_admissions += 1
        if not (r.discharge_prescription and r.discharge_prescription.items):
            continue
        counts = Counter(
            _dedup_key(str(it.get("drug_name", "") or ""))
            for it in r.discharge_prescription.items
            if it.get("drug_name")
        )
        dups = {k: c for k, c in counts.items() if c > 1}
        if dups:
            offenders.append((r.patient.patient_id, r.encounters[0].encounter_id, dups))

    assert total_admissions > 0, (
        "cohort produced no inpatient admissions — test is vacuous. Update p / seed / time_range."
    )

    assert not offenders, (
        f"{len(offenders)}/{total_admissions} inpatient admissions had "
        f"duplicate drug_name in discharge_prescription.items. This means "
        f"the exact-name dedup in _build_discharge_rx regressed. First 5:\n"
        + "\n".join(f"  pid={pid}  enc={enc}  dup_counts={dups}" for pid, enc, dups in offenders[:5])
    )
