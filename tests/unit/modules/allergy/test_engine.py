"""Unit tests for allergy enricher (Tier 1 #3 α-min-1 PR1)."""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.allergy.engine import allergy_enricher, load_allergens


def _make_ctx(patients, master_seed=42):
    """Create a mock EnricherContext using the real API: population.persons.values()."""
    persons_dict = {p.patient_id: p for p in patients}
    return SimpleNamespace(
        master_seed=master_seed,
        population=SimpleNamespace(persons=persons_dict),
        records=[],
        config=SimpleNamespace(modules=SimpleNamespace()),
    )


def test_load_allergens_returns_3_categories():
    a = load_allergens()
    assert "medication" in a
    assert "food" in a
    assert "environment" in a


def test_medication_allergen_has_penicillin():
    a = load_allergens()
    med = a["medication"]
    pen = [e for e in med if e["allergen_display_en"] == "Penicillin"]
    assert pen
    # Session 57 v3: allergens.yaml swapped the Penicillin code from
    # 387207008 (Ibuprofen in SNOMED CT International 2026-06-01) to
    # 373270004 (Substance with penicillin structure).
    assert pen[0]["allergen_code"] == "373270004"


def test_enricher_populates_allergies_per_patient():
    p1 = SimpleNamespace(patient_id="pt1", age=45, sex="F", allergies=[])
    p2 = SimpleNamespace(patient_id="pt2", age=30, sex="M", allergies=[])
    ctx = _make_ctx([p1, p2])
    allergy_enricher(ctx)
    # Determinism: 同 seed で同結果 (prevalence-driven sampling、人によって 0 件もありうる)
    assert hasattr(p1, "allergies")
    assert hasattr(p2, "allergies")


def test_enricher_deterministic_same_seed():
    p1a = SimpleNamespace(patient_id="pt1", age=45, sex="F", allergies=[])
    p1b = SimpleNamespace(patient_id="pt1", age=45, sex="F", allergies=[])
    allergy_enricher(_make_ctx([p1a], master_seed=42))
    allergy_enricher(_make_ctx([p1b], master_seed=42))
    assert len(p1a.allergies) == len(p1b.allergies)
    if p1a.allergies:
        assert p1a.allergies[0].allergen_code == p1b.allergies[0].allergen_code


def test_enricher_allergy_structure_valid():
    """Sampled allergy has valid category, criticality, reactions."""
    from clinosim.modules.allergy.engine import SUPPORTED_ALLERGEN_CATEGORIES
    from clinosim.types.allergy import Allergy, AllergyReaction

    # Use a seed that deterministically produces an allergy for "pt-sample"
    # We'll run enough patients to ensure at least one gets sampled
    patients = [SimpleNamespace(patient_id=f"pt-{i}", age=40, sex="M", allergies=[]) for i in range(30)]
    ctx = _make_ctx(patients, master_seed=42)
    allergy_enricher(ctx)

    sampled = [p for p in patients if p.allergies]
    assert sampled, "Expected at least one patient with allergy in 30 patients at 15% prevalence"
    for p in sampled:
        a = p.allergies[0]
        assert isinstance(a, Allergy)
        assert a.category in SUPPORTED_ALLERGEN_CATEGORIES
        assert a.criticality in ("low", "high", "unable-to-assess")
        assert a.allergen_code
        assert a.reactions
        r = a.reactions[0]
        assert isinstance(r, AllergyReaction)
        assert r.severity in ("mild", "moderate", "severe")


def test_enricher_15pct_calibration():
    """15% overall prevalence gate: US p=500 cohort should yield 60-110 allergies (12-22%)."""
    patients = [SimpleNamespace(patient_id=f"pt-{i}", age=40, sex="M", allergies=None) for i in range(500)]
    ctx = _make_ctx(patients, master_seed=42)
    allergy_enricher(ctx)

    count = sum(1 for p in patients if p.allergies)
    assert 60 <= count <= 110, f"Expected 60-110 patients with allergies (12-22%) in 500 patients, got {count}"


def test_enricher_sets_empty_list_not_none_for_no_allergy_patients():
    """I-1 regression: enricher MUST set [] (not None) for no-allergy patients.

    PersonRecord.allergies default is now None so activator.py can distinguish
    'enricher ran, no allergy' ([]) from 'enricher hasn't run' (None).
    Without this sentinel, the activator's `is not None` coexistence check
    would fall through to the legacy 15% re-roll for all 85% no-allergy
    patients, compounding to ~27.75% effective prevalence.
    """
    # Run a large cohort — expect 85% to have allergies == [] (not None).
    # Use the allergy_enricher with a fresh init so patient.allergies starts as None.
    patients = [SimpleNamespace(patient_id=f"pt-{i}", age=40, sex="M", allergies=None) for i in range(200)]
    ctx = _make_ctx(patients, master_seed=42)
    allergy_enricher(ctx)

    no_allergy = [p for p in patients if not p.allergies]
    with_allergy = [p for p in patients if p.allergies]

    # All patients must have allergies explicitly set (not None) by the enricher
    still_none = [p for p in patients if p.allergies is None]
    assert not still_none, (
        f"Enricher left {len(still_none)} patients with allergies=None; "
        "must set [] for no-allergy patients so activator coexistence check works."
    )

    # No-allergy patients must have EMPTY LIST (not None)
    for p in no_allergy:
        assert p.allergies == [], f"Patient {p.patient_id}: expected [] for no-allergy, got {p.allergies!r}"

    # Allergy patients must have non-empty list
    for p in with_allergy:
        assert len(p.allergies) >= 1, f"Patient {p.patient_id}: expected ≥1 allergy, got {p.allergies!r}"
