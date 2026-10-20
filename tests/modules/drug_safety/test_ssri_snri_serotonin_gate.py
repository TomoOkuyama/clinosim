"""SSRI + SNRI serotonin-syndrome gate.

Audit s103 (p=2000 US 5y seed=42) flagged POP-000601 (21M, GAD-7
severe) carrying ``[Sertraline, Duloxetine, Alprazolam]`` concurrently
in ``current_medications``. Chronic SSRI + SNRI co-prescription is
not standard-of-care — both mechanisms raise 5-HT availability and
compound serotonin-syndrome risk without evidence of additive
efficacy. The gate is realised as a class × class rule in
``drug_safety/reference_data/contraindications.yaml``
(``ssri-plus-snri`` severity=major) backed by the drug-class
mappings this PR adds to ``drug_classes.yaml``.

Scope: ``ssri + snri`` only. Benzodiazepines gain class mappings
(``benzodiazepine`` / ``anxiolytic``) for future rules but no
BZD-related rule fires here — short-term BZD augmentation of SSRI
is per APA/NICE guidelines, so SSRI + BZD stays ``allowed`` in this
PR.
"""

from __future__ import annotations

import pytest

from clinosim.modules.drug_safety.classifier import resolve_classes
from clinosim.modules.drug_safety.engine import (
    check_candidate_against_active,
    check_pair,
)

# ---------------- class mappings


@pytest.mark.unit
@pytest.mark.parametrize(
    "drug,expected_class",
    [
        ("Sertraline", "ssri"),
        ("Escitalopram", "ssri"),
        ("Fluoxetine", "ssri"),
        ("Paroxetine", "ssri"),
        ("Duloxetine", "snri"),
        ("Venlafaxine", "snri"),
        ("Mirtazapine", "atypical_antidepressant"),
    ],
)
def test_antidepressant_class_mapping(drug: str, expected_class: str) -> None:
    classes = resolve_classes(drug)
    assert expected_class in classes
    # Every antidepressant also tagged as "antidepressant" for future
    # umbrella rules (e.g. elderly-caution).
    assert "antidepressant" in classes


@pytest.mark.unit
@pytest.mark.parametrize("drug", ["Lorazepam", "Alprazolam", "Diazepam", "Clonazepam"])
def test_benzodiazepine_class_mapping(drug: str) -> None:
    classes = resolve_classes(drug)
    assert "benzodiazepine" in classes
    assert "anxiolytic" in classes


@pytest.mark.unit
def test_mirtazapine_is_not_tagged_as_ssri_or_snri() -> None:
    """Mirtazapine is a serotonergic antagonist (5-HT2/5-HT3 + α2),
    not a reuptake inhibitor — adding it on top of an SSRI/SNRI is the
    APA/VA-DoD-recommended augmentation path and MUST NOT trigger the
    ssri-plus-snri gate."""
    classes = resolve_classes("Mirtazapine")
    assert "ssri" not in classes
    assert "snri" not in classes


@pytest.mark.unit
def test_japanese_alias_resolves_to_same_class() -> None:
    """Katakana alias path is the only route for JP-locale chronic
    medications emitted via ``drug_names_ja.yaml``."""
    assert resolve_classes("デュロキセチン") == resolve_classes("Duloxetine")
    assert resolve_classes("セルトラリン") == resolve_classes("Sertraline")
    assert resolve_classes("ロラゼパム") == resolve_classes("Lorazepam")


# ---------------- rule firing


@pytest.mark.unit
def test_ssri_plus_snri_fires_major() -> None:
    v = check_pair("Sertraline", "Duloxetine")
    assert v.severity == "major"
    assert v.rule_id == "ssri-plus-snri"
    assert v.rationale_en is not None
    assert v.rationale_ja is not None


@pytest.mark.unit
def test_ssri_plus_snri_order_independent() -> None:
    a = check_pair("Sertraline", "Duloxetine")
    b = check_pair("Duloxetine", "Sertraline")
    assert a.severity == b.severity == "major"
    assert a.rule_id == b.rule_id


@pytest.mark.unit
@pytest.mark.parametrize(
    "ssri,snri",
    [
        ("Sertraline", "Duloxetine"),
        ("Escitalopram", "Venlafaxine"),
        ("Fluoxetine", "Duloxetine"),
        ("Paroxetine", "Venlafaxine"),
    ],
)
def test_ssri_x_snri_all_pairs_fire(ssri: str, snri: str) -> None:
    """Every (SSRI, SNRI) pair in the yaml must fire — no gap matrix."""
    v = check_pair(ssri, snri)
    assert v.severity == "major"
    assert v.rule_id == "ssri-plus-snri"


@pytest.mark.unit
def test_ssri_plus_atypical_is_allowed() -> None:
    """SSRI + Mirtazapine is the guideline-recommended augmentation
    path (APA 2010 — "California rocket fuel"). It MUST stay allowed
    so the sampler can prescribe both."""
    v = check_pair("Sertraline", "Mirtazapine")
    assert v.severity == "allowed"


@pytest.mark.unit
def test_snri_plus_atypical_is_allowed() -> None:
    v = check_pair("Duloxetine", "Mirtazapine")
    assert v.severity == "allowed"


@pytest.mark.unit
def test_ssri_plus_benzodiazepine_is_allowed() -> None:
    """Short-term BZD augmentation of SSRI is per APA 2010 / NICE
    CG113 for severe GAD and acute anxiety-crisis periods. The chronic
    daily-BZD duration concern is a separate (not-yet-implemented)
    longitudinal rule, so the pair-level verdict here stays allowed."""
    v = check_pair("Sertraline", "Alprazolam")
    assert v.severity == "allowed"


@pytest.mark.unit
def test_snri_plus_benzodiazepine_is_allowed() -> None:
    v = check_pair("Duloxetine", "Lorazepam")
    assert v.severity == "allowed"


@pytest.mark.unit
def test_two_ssris_is_allowed_by_this_pr() -> None:
    """Dual-SSRI stacking is also not standard practice but is not
    captured by the ssri-plus-snri rule — if a dual-SSRI gate is
    wanted, it needs its own ssri-plus-ssri entry. Verifying here so
    this PR's scope is explicit."""
    v = check_pair("Sertraline", "Escitalopram")
    assert v.severity == "allowed"


# ---------------- integration via check_candidate_against_active
# (same path the activator CPOE gate uses)


@pytest.mark.unit
def test_check_candidate_against_active_drops_snri_when_ssri_present() -> None:
    """Replay the audit scenario: Sertraline is already an accepted
    chronic home med; the sampler then offers Duloxetine. The gate
    should return a major-severity verdict so the activator drops
    the SNRI."""
    verdicts = check_candidate_against_active("Duloxetine", ["Sertraline"])
    assert any(v.rule_id == "ssri-plus-snri" and v.severity == "major" for v in verdicts)


@pytest.mark.unit
def test_check_candidate_against_active_drops_ssri_when_snri_present() -> None:
    """Reverse order — SNRI first, then SSRI offered. Gate fires the
    same way (order-independent)."""
    verdicts = check_candidate_against_active("Sertraline", ["Duloxetine"])
    assert any(v.rule_id == "ssri-plus-snri" and v.severity == "major" for v in verdicts)


@pytest.mark.unit
def test_check_candidate_against_active_does_not_drop_atypical_augmentation() -> None:
    """Mirtazapine offered on top of Sertraline is the guideline
    augmentation path — gate must stay allowed so the sampler keeps
    both."""
    verdicts = check_candidate_against_active("Mirtazapine", ["Sertraline"])
    # Any non-allowed verdict here would block guideline augmentation.
    assert all(v.severity == "allowed" for v in verdicts)


@pytest.mark.unit
def test_check_candidate_against_active_does_not_drop_benzodiazepine_add_on() -> None:
    """BZD offered on top of SSRI is a per-guideline short-term
    augmentation for severe GAD — pair-level verdict stays allowed in
    this PR."""
    verdicts = check_candidate_against_active("Alprazolam", ["Sertraline"])
    assert all(v.severity == "allowed" for v in verdicts)
