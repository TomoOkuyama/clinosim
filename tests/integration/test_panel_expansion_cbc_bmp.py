"""Integration test: CBC and BMP panel orders expand into canonical
component child orders (PR1 of CBC/BMP panel expansion).

Spec: docs/superpowers/specs/2026-06-23-cbc-bmp-panel-expansion-design.md

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


def _panel_parent_orders(record, parent_name: str) -> list:
    """Orders whose display_name equals the panel name (e.g. "CBC", "BMP")."""
    return [o for o in record.orders if o.display_name == parent_name]


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
        # Group panel children by parent (order_id pattern: f"{parent}-{comp}").
        # A parent is any RESULTED panel order whose children are also in record.orders.
        parents = {
            o.order_id
            for o in record.orders
            if o.display_name in {"CBC", "BMP", "ABG"} and o.status == OrderStatus.RESULTED
        }
        for parent_id in parents:
            children = [o for o in record.orders if o.order_id.startswith(parent_id + "-")]
            if not children:
                continue
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
        bmp_parents = [o for o in record.orders if o.display_name == "BMP" and o.status == OrderStatus.RESULTED]
        for parent in bmp_parents:
            cl_children = [o for o in record.orders if o.order_id == f"{parent.order_id}-Cl"]
            ca_children = [o for o in record.orders if o.order_id == f"{parent.order_id}-Ca"]
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
def test_panel_parents_marked_resulted_no_scalar_observation():
    """The PLACED→RESULTED transition on the parent CBC/BMP order
    (inpatient.py:584) is what prevents the parent itself from emitting a
    scalar Observation alongside its children. Two checks:
      1. Every parent order with display_name in {"CBC", "BMP"} is in
         RESULTED status (not PLACED, not CANCELLED).
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
        # Check 1: every CBC/BMP parent ended up RESULTED.
        for parent_name in ("CBC", "BMP"):
            parents = _panel_parent_orders(record, parent_name)
            assert parents, f"DKA patient should carry at least one {parent_name} order per protocol; found none."
            for p in parents:
                assert p.status == OrderStatus.RESULTED, (
                    f"Panel parent {parent_name} should be RESULTED, "
                    f"got status={p.status}; the panel-expansion loop at "
                    f"inpatient.py:584 must mark it after extending children."
                )
                assert p.result is None, (
                    f"Panel parent {parent_name} must not carry a scalar OrderResult (children emit individually)."
                )

        # Check 2: no result row is labelled with a panel name.
        emitted = _emitted_lab_names(record)
        assert not (emitted & {"CBC", "BMP"}), (
            f"Panel names leaked into emitted labs: "
            f"{emitted & {'CBC', 'BMP'}} — the scalar fallback should "
            f"have skipped them."
        )


@pytest.mark.integration
def test_cerebral_infarction_individual_hb_plt_orders_removed():
    """PR2: cerebral_infarction.yaml lines 139-140 (individual {test: "Hb"}
    and {test: "Plt"} stat orders) are deleted. The CBC panel order at
    line 126 supplies both analytes via its panel children, so no
    individual Hb / Plt order should appear in any cerebral_infarction
    patient's record. (Panel-child orders are allowed — their order_id
    ends in "-Hb" or "-Plt".)"""
    scenario = ForcedScenario(
        disease_id="cerebral_infarction",
        count=5,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)
    for record in dataset.patients:
        for order in record.orders:
            if order.display_name in {"Hb", "Plt"}:
                comp = order.display_name
                assert order.order_id.endswith(f"-{comp}"), (
                    f"Found individual {comp} order {order.order_id} — "
                    f"PR2 deletes these from cerebral_infarction.yaml "
                    f"lines 139-140; only CBC panel children should "
                    f"emit {comp} in this protocol."
                )


@pytest.mark.integration
def test_cerebral_infarction_cbc_panel_still_emits_all_four_components():
    """Regression guard: after PR2 removes individual Hb / Plt, the CBC
    panel order at cerebral_infarction.yaml line 126 must still emit
    all four canonical components via its children. This protects
    against accidentally deleting too many lines in the YAML edit."""
    scenario = ForcedScenario(
        disease_id="cerebral_infarction",
        count=5,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)
    for record in dataset.patients:
        emitted = {
            o.result.lab_name for o in record.orders if o.result is not None and o.result.lab_name in CBC_COMPONENTS
        }
        assert CBC_COMPONENTS.issubset(emitted), (
            f"After PR2 cerebral_infarction must still emit {CBC_COMPONENTS}; missing {CBC_COMPONENTS - emitted}."
        )
