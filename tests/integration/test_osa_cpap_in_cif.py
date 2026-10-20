"""Phase 4d — OSA CPAP + polysomnography cohort integration.

Phase 4d adds a G47.30 chronic_followup block with procedures: field.
The deterministic emit behavior is pinned by the unit tests under
tests/simulator/outpatient/. This integration test narrows to the
non-OSA invariance (Review Focus #2) because G47.30 is assigned by
`clinosim.modules.metabolic.engine` at encounter / activation time, not
at `generate_population` time — the cohort generator alone produces zero
G47.30 patients at p=500 (verified empirically).
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import generate_population

CPAP_CODE = "99503"
POLYSOMNOGRAPHY_CODE = "95810"


def _collect_procedure_codes(person):
    codes: list[str] = []
    for enc_history_rec in getattr(person, "encounter_history", []) or []:
        procedures = getattr(enc_history_rec, "procedures", None) or []
        for p in procedures:
            codes.append(getattr(p, "procedure_code", "") or "")
    return codes


@pytest.mark.integration
def test_non_osa_adults_never_emit_cpap_or_polysomnography():
    """Review Focus #2 — clinical_scope invariance via chronic_followup.yaml.
    A non-G47.30 adult must never see CPAP or polysomnography ProcedureRecord
    emitted via the Phase 4d path (chronic_followup block is exact-key, no
    sub-code bleed, and only G47.30 declares these procedures)."""
    registry = generate_population(
        size=500, country="US", rng=np.random.default_rng(42), base_year=2024
    )
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")

    forbidden = {CPAP_CODE, POLYSOMNOGRAPHY_CODE}
    for person in registry.persons.values():
        if person.age < 18:
            continue
        if any(c.startswith("G47.30") for c in person.chronic_conditions):
            continue
        on_forbidden = [c for c in _collect_procedure_codes(person) if c in forbidden]
        assert not on_forbidden, (
            f"non-OSA person {person.person_id} emitted {on_forbidden}"
        )
