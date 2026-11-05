"""Integration test: CBC and BMP panel orders expand into canonical
component child orders (PR1 of CBC/BMP panel expansion).

Spec: docs/history/specs-archive/2026-06-23-cbc-bmp-panel-expansion-design.md

The CIFPatientRecord stores `orders` and `lab_results` as flat patient-level
lists (not encounter-nested) — see clinosim/types/output.py. Tests therefore
walk record.orders / record.lab_results directly.
"""

import pytest

from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import OrderStatus

CBC_COMPONENTS = {"WBC", "Hb", "Hct", "Plt"}
# Phase 1 (BMP Cl/Ca physiology) added Cl and Ca to derive_lab_values, so
# BMP now emits the full canonical 8. Pre-Phase-1, the emit set was 6 and
# Cl/Ca were silently dropped — see git log for the prior assertions.
BMP_COMPONENTS_EMITTED = {"Na", "K", "Cl", "HCO3", "BUN", "Creatinine", "Glucose", "Ca"}


def _emitted_lab_names(record) -> set[str]:
    """Set of lab_name values across every RESULTED order on the record."""
    return {o.result.lab_name for o in record.orders if o.result is not None and o.result.lab_name}


def _expanded_panels(record) -> dict[str, list]:
    """Component orders of each expanded panel order, keyed by the panel
    order's id (component ids are ``f"{panel_order_id}-{component}"``)."""
    groups: dict[str, list] = {}
    for o in record.orders:
        suffix = f"-{o.display_name}"
        if o.panel_key and o.order_id.endswith(suffix):
            groups.setdefault(o.order_id[: -len(suffix)], []).append(o)
    return groups


@pytest.mark.integration
def test_cerebral_infarction_cbc_emits_four_components():
    """A cerebral_infarction patient orders {test: "CBC"} at admission;
    after PR1 that order expands into a panel parent (RESULTED) plus
    four child orders that produce WBC, Hb, Hct, and Plt OrderResults."""
    scenario = ForcedScenario(
        disease_id="cerebral_infarction",
        count=2,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    assert len(dataset.patients) == 2
    for record in dataset.patients:
        emitted = _emitted_lab_names(record)
        assert CBC_COMPONENTS.issubset(emitted), (
            f"Expected CBC components {CBC_COMPONENTS} in cerebral_infarction "
            f"emitted labs, got intersection {CBC_COMPONENTS & emitted}"
        )


@pytest.mark.integration
def test_dka_bmp_emits_eight_components_full_canonical():
    """A DKA patient orders {test: "BMP"} at admission; PR1 expanded it into
    eight child orders and Phase 1 (Cl/Ca added to derive_lab_values) makes
    all eight components RESULT — full BMP canonical 8."""
    scenario = ForcedScenario(
        disease_id="diabetic_ketoacidosis",
        count=2,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        emitted = _emitted_lab_names(record)
        assert BMP_COMPONENTS_EMITTED.issubset(emitted), (
            f"Expected full canonical BMP components {BMP_COMPONENTS_EMITTED}, "
            f"got intersection {BMP_COMPONENTS_EMITTED & emitted}"
        )


@pytest.mark.integration
def test_panel_children_cancellation_is_per_specimen():
    """Specimen rejection is a per-specimen event, not per-analyte: when a
    panel parent's specimen is rejected, *every* child for that parent moves
    to CANCELLED; when a specimen is accepted, no child of that parent gets
    a per-analyte specimen rejection.

    The per-parent sub-RNG (simulator/seeding.py panel_specimen_seed) draws
    specimen rejection once per parent, so within a parent's child set the
    cancellation pattern is all-or-nothing — never a mixture of CANCELLED
    and RESULTED siblings.
    """
    scenario = ForcedScenario(
        disease_id="cerebral_infarction",
        count=10,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        # One specimen per expanded panel order (component ids f"{panel}-{comp}").
        for parent_id, children in _expanded_panels(record).items():
            statuses = {c.status for c in children}
            # Either every child cancelled (specimen rejected) OR no child is
            # cancelled (specimen accepted). The "Cl/Ca dropped" case stays
            # at PLACED, not CANCELLED — those are silent drops, not rejections.
            has_cancelled = any(c.status == OrderStatus.CANCELLED for c in children)
            has_non_cancelled = any(c.status != OrderStatus.CANCELLED for c in children)
            assert not (has_cancelled and has_non_cancelled), (
                f"Mixed CANCELLED/non-CANCELLED siblings for parent "
                f"{parent_id}: statuses={statuses}. Specimen rejection must "
                f"be per-specimen, not per-analyte."
            )


@pytest.mark.integration
def test_dka_bmp_cl_ca_children_now_resulted():
    """Phase 1 (Cl/Ca added to derive_lab_values) inverts the prior
    behaviour: Cl and Ca BMP children — previously left at PLACED with no
    result because derive_lab_values dropped them — now RESULT alongside
    their six siblings, completing the canonical 8."""
    scenario = ForcedScenario(
        disease_id="diabetic_ketoacidosis",
        count=2,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        bmp_panels = [kids for kids in _expanded_panels(record).values() if kids[0].panel_key == "BMP"]
        assert bmp_panels, "DKA patient should carry a BMP order per protocol"
        for children in bmp_panels:
            cl_children = [o for o in children if o.display_name == "Cl"]
            ca_children = [o for o in children if o.display_name == "Ca"]
            # Specimen acceptance path: every Cl/Ca child should be
            # RESULTED with a numerical result. Specimen rejection path
            # (per-parent sub-RNG cancels all children together) stays
            # covered by test_panel_children_cancellation_is_per_specimen.
            for child in cl_children + ca_children:
                if child.status == OrderStatus.CANCELLED:
                    # Specimen rejected — siblings also CANCELLED, no result
                    continue
                assert child.status == OrderStatus.RESULTED, (
                    f"BMP child {child.order_id} ({child.display_name}) "
                    f"should be RESULTED after Phase 1 (Cl/Ca emit) — "
                    f"got {child.status}."
                )
                assert child.result is not None, (
                    f"BMP child {child.order_id} ({child.display_name}) has no result despite being RESULTED."
                )


@pytest.mark.integration
def test_a_panel_order_is_replaced_by_its_components():
    """Issue #2582: an expanded CBC / BMP order is replaced in the order list
    by its component orders, which carry the panel as ``panel_key`` (so the
    FHIR builder emits one panel ServiceRequest). Two checks:
      1. No order is left under the panel name, and components of both
         panels are present.
      2. No OrderResult.lab_name is "CBC" or "BMP" — the scalar fallback
         must never fire on a panel name.
    """
    scenario = ForcedScenario(
        disease_id="diabetic_ketoacidosis",
        count=2,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        assert not [o for o in record.orders if o.display_name in {"CBC", "BMP"}]
        panels = {kids[0].panel_key for kids in _expanded_panels(record).values()}
        assert {"CBC", "BMP"} <= panels, f"expected CBC and BMP components, got panels {panels}"

        emitted = _emitted_lab_names(record)
        assert not (emitted & {"CBC", "BMP"}), (
            f"Panel names leaked into emitted labs: "
            f"{emitted & {'CBC', 'BMP'}} — the scalar fallback should "
            f"have skipped them."
        )
