"""Issue #1756 — K76.0 (NAFLD) + F10.x (alcohol use disorder) are
mutually exclusive by definition: NAFLD is the fatty-liver phenotype
in patients WITHOUT significant alcohol consumption. The correct
hepatic ICD for an alcohol-use-disorder patient with fatty liver is
K70.x (alcoholic liver disease).

Pre-fix, 305 patients in US p=10k seed=42 5y carried both K76.0 and
F10.20 because the ``k76_0_nafld_enricher`` consulted BMI + DM only
and did not check whether the person already had F10 on their
problem list.

Fix: suppress K76.0 assignment when the person's chronic_conditions
already carry F10.x. K70.x assignment for the fatty-liver phenotype
of F10 patients is a separate concern (the K70 onset path currently
produces zero patients in the cohort — tracked under #1608).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.metabolic.engine import (
    _derive_nafld_assignment,
    k76_0_nafld_enricher,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers — a minimal PopulationRegistry + PersonRecord shape so the
# enricher's attribute access works without pulling the full type graph.
# ---------------------------------------------------------------------------


def _mkperson(pid: str, bmi: float, chronic: list[str]) -> SimpleNamespace:
    return SimpleNamespace(person_id=pid, bmi=bmi, chronic_conditions=list(chronic))


def _mkctx(persons: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(population=SimpleNamespace(persons={p.person_id: p for p in persons}))


# ---------------------------------------------------------------------------
# _derive_nafld_assignment: direct suppression on F10 presence
# ---------------------------------------------------------------------------


def test_derive_nafld_suppressed_when_f10_20_present():
    """A person with F10.20 (alcohol UD, uncomplicated) on their problem
    list must not be assigned K76.0 regardless of BMI / DM status."""
    for pid in [f"POP-{n:06d}" for n in range(50)]:
        code = _derive_nafld_assignment(pid, bmi=35.0, chronic=["F10.20", "E11.9"])
        assert code is None, f"{pid}: K76.0 must be suppressed when F10.20 is present; got {code!r}"


def test_derive_nafld_suppressed_when_bare_f10_present():
    """A ``F10`` bare code (without subcode) must also suppress K76.0 —
    the gate matches by prefix, not exact code."""
    code = _derive_nafld_assignment("POP-000001", bmi=35.0, chronic=["F10"])
    assert code is None


def test_derive_nafld_suppressed_when_f10_subcode_variants_present():
    """F10.10 (abuse), F10.21 (dependence, in remission), F10.230 (with
    withdrawal) — any F10 subcode must suppress K76.0. Prefix match."""
    for sub in ["F10.10", "F10.21", "F10.230", "F10.2990"]:
        code = _derive_nafld_assignment("POP-000001", bmi=35.0, chronic=[sub])
        assert code is None, f"K76.0 suppression must apply to {sub} (F10 prefix)"


def test_derive_nafld_fires_normally_when_f10_absent():
    """Pre-fix behaviour preserved for the common case: a person
    without F10 and with BMI ≥ 30 is assigned K76.0 via the usual
    BMI + DM-weighted Bernoulli draw. Scan 200 person_ids to find
    at least one assignment (RNG-neutral SHA Bernoulli with
    probability ≈ 0.60 — expected ~120 of 200)."""
    assignments = sum(
        1 for n in range(200) if _derive_nafld_assignment(f"POP-{n:06d}", bmi=35.0, chronic=["E11.9"]) == "K76.0"
    )
    assert assignments > 50, (
        f"K76.0 must still fire for F10-free patients; got {assignments}/200 (expected ~120 at BMI 35 + E11.9)"
    )


# ---------------------------------------------------------------------------
# k76_0_nafld_enricher end-to-end — guard holds at the enricher layer
# ---------------------------------------------------------------------------


def test_enricher_does_not_append_k76_to_f10_persons():
    f10_persons = [_mkperson(f"POP-F10-{i:03d}", 35.0, ["F10.20", "E11.9"]) for i in range(30)]
    non_f10_persons = [_mkperson(f"POP-NON-{i:03d}", 35.0, ["E11.9"]) for i in range(30)]
    ctx = _mkctx(f10_persons + non_f10_persons)
    k76_0_nafld_enricher(ctx)
    # F10 cohort: zero K76.0 assignments
    f10_k76 = sum(1 for p in f10_persons if "K76.0" in p.chronic_conditions)
    assert f10_k76 == 0, f"F10 cohort must have zero K76.0 after enricher; got {f10_k76}"
    # Non-F10 cohort: some K76.0 assignments (sanity check, not a tight bound)
    non_f10_k76 = sum(1 for p in non_f10_persons if "K76.0" in p.chronic_conditions)
    assert non_f10_k76 > 5, f"Non-F10 cohort must retain K76.0 assignment pattern; got {non_f10_k76}/30"


def test_enricher_leaves_pre_existing_k76_on_f10_person_untouched():
    """Idempotency: if a person already carries K76.0 (hypothetically
    from a legacy sampler path) AND has F10, the enricher does not
    duplicate or remove the entry. The guard only prevents NEW
    assignments; cleanup of pre-existing contradictions is a separate
    post-hoc pass (tracked in follow-up)."""
    person = _mkperson("POP-LEGACY", 35.0, ["F10.20", "K76.0"])
    k76_0_nafld_enricher(_mkctx([person]))
    assert person.chronic_conditions.count("K76.0") == 1
    assert "F10.20" in person.chronic_conditions
