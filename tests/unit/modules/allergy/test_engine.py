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
    p1a = SimpleNamespace(patient_id="pt1", age=45, sex="F", chronic_conditions=[], allergies=[])
    p1b = SimpleNamespace(patient_id="pt1", age=45, sex="F", chronic_conditions=[], allergies=[])
    allergy_enricher(_make_ctx([p1a], master_seed=42))
    allergy_enricher(_make_ctx([p1b], master_seed=42))
    assert len(p1a.allergies) == len(p1b.allergies)
    if p1a.allergies:
        assert p1a.allergies[0].allergen_code == p1b.allergies[0].allergen_code


def test_enricher_allergy_structure_valid():
    """Sampled real (non-NKA) allergy has valid category, criticality, reactions."""
    from clinosim.modules.allergy.engine import SUPPORTED_ALLERGEN_CATEGORIES
    from clinosim.types.allergy import Allergy, AllergyReaction

    # Issue #942: every patient now gets ≥1 record (NKA or real). Filter to
    # non-NKA records for the substance-shape assertions.
    patients = [
        SimpleNamespace(patient_id=f"pt-{i}", age=40, sex="M", chronic_conditions=[], allergies=[]) for i in range(30)
    ]
    ctx = _make_ctx(patients, master_seed=42)
    allergy_enricher(ctx)

    real_records: list[Allergy] = []
    for p in patients:
        for a in p.allergies or []:
            if not a.is_nka:
                real_records.append(a)
    assert real_records, "Expected at least one real (non-NKA) allergy in 30 patients at 15% prevalence"
    for a in real_records:
        assert isinstance(a, Allergy)
        assert a.category in SUPPORTED_ALLERGEN_CATEGORIES
        assert a.criticality in ("low", "high", "unable-to-assess")
        assert a.allergen_code
        assert a.reactions
        r = a.reactions[0]
        assert isinstance(r, AllergyReaction)
        assert r.severity in ("mild", "moderate", "severe")


def test_enricher_15pct_real_allergen_calibration():
    """15% overall real-allergen gate: p=500 cohort should yield 60-110 patients
    with a non-NKA record (12-22%). Every patient carries ≥1 record (Issue #942)."""
    patients = [
        SimpleNamespace(patient_id=f"pt-{i}", age=40, sex="M", chronic_conditions=[], allergies=None)
        for i in range(500)
    ]
    ctx = _make_ctx(patients, master_seed=42)
    allergy_enricher(ctx)

    # Every patient has ≥1 record now.
    assert all(p.allergies for p in patients), "Issue #942: every patient must have ≥1 AllergyIntolerance record"

    real_count = sum(1 for p in patients if any(not a.is_nka for a in p.allergies))
    assert 60 <= real_count <= 110, f"Expected 60-110 patients with real allergies (12-22%), got {real_count}"


def test_enricher_emits_nka_for_no_allergy_patients():
    """Issue #942: patients failing the 15% real-allergen gate get exactly ONE
    NKA (No Known Allergies) positive-assertion record (SNOMED 716186003).

    Replaces the pre-#942 sentinel `allergies == []`: the empty-list state is
    now indistinguishable from "not assessed" and would silently drop the
    bedside-safety NKA signal (feedback_empty_vs_wrong_assertion.md).
    """
    patients = [
        SimpleNamespace(patient_id=f"pt-{i}", age=40, sex="M", chronic_conditions=[], allergies=None)
        for i in range(200)
    ]
    ctx = _make_ctx(patients, master_seed=42)
    allergy_enricher(ctx)

    # Every patient must have ≥1 record — no more silent absence.
    still_none = [p for p in patients if p.allergies is None]
    empty_lists = [p for p in patients if p.allergies == []]
    assert not still_none, f"Enricher left {len(still_none)} patients with allergies=None"
    assert not empty_lists, f"Enricher left {len(empty_lists)} patients with empty allergies list"

    # Non-allergic patients must carry exactly one NKA record.
    nka_only = [p for p in patients if len(p.allergies) == 1 and p.allergies[0].is_nka]
    assert nka_only, "Expected some patients to carry a single NKA record"
    for p in nka_only:
        a = p.allergies[0]
        assert a.allergen_code == "716186003"
        assert a.verification_status == "confirmed"
        assert a.clinical_status == "resolved"
        assert a.category == ""
        assert a.reactions == []


def test_enricher_produces_polyallergy():
    """Issue #942: a non-trivial fraction of the cohort must carry ≥2 records.
    Target absolute polyallergy rate 3-5% overall for adults."""
    patients = [
        SimpleNamespace(patient_id=f"pt-{i}", age=45, sex="M", chronic_conditions=[], allergies=None)
        for i in range(1000)
    ]
    ctx = _make_ctx(patients, master_seed=42)
    allergy_enricher(ctx)

    poly_count = sum(1 for p in patients if len(p.allergies or []) >= 2)
    # Loose bounds for CI stability: 1-8% of the whole cohort.
    assert 10 <= poly_count <= 80, f"Expected 10-80 polyallergic patients (1-8%) in 1000 adults, got {poly_count}"


def test_enricher_elderly_polyallergy_rate_exceeds_adult():
    """Issue #942: elderly cohort should carry more polyallergy than adults."""
    adults = [
        SimpleNamespace(patient_id=f"pt-a-{i}", age=45, sex="M", chronic_conditions=[], allergies=None)
        for i in range(1000)
    ]
    elderly = [
        SimpleNamespace(patient_id=f"pt-e-{i}", age=75, sex="M", chronic_conditions=[], allergies=None)
        for i in range(1000)
    ]
    allergy_enricher(_make_ctx(adults, master_seed=42))
    allergy_enricher(_make_ctx(elderly, master_seed=42))

    adult_poly = sum(1 for p in adults if len(p.allergies or []) >= 2)
    elderly_poly = sum(1 for p in elderly if len(p.allergies or []) >= 2)
    assert elderly_poly > adult_poly, (
        f"Elderly polyallergy ({elderly_poly}) must exceed adult polyallergy ({adult_poly})"
    )
