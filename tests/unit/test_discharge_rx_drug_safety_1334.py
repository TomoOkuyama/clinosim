"""Issue #1334 part 2 (META #1392 Cluster A) — discharge_rx drug_safety gate.

Post-CVA discharge Rx builder emitted DOAC + Aspirin + Clopidogrel triple-
therapy without a drug_safety gate — the builder had no
``check_candidate_against_active`` call. This test suite covers:

- Pair rule ``doac-plus-p2y12`` fires when Apixaban is combined with
  Clopidogrel (previously only vka + antiplatelet fired).
- Discharge-Rx builder gate drops a P2Y12 candidate on a patient whose
  chronic current_medications already carry Apixaban (DOAC).
- Existing DAPT patterns (Aspirin + Clopidogrel alone, no DOAC) still
  emit unchanged — the gate is scoped to actual rule triggers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from clinosim.modules import drug_safety


def test_apixaban_plus_clopidogrel_pair_rule_fires():
    v = drug_safety.check_pair("Apixaban", "Clopidogrel")
    assert v.severity == "contraindicated"
    assert v.rule_id == "doac-plus-p2y12"


def test_rivaroxaban_plus_prasugrel_pair_rule_fires():
    v = drug_safety.check_pair("Rivaroxaban", "Prasugrel")
    assert v.severity == "contraindicated"


def test_apixaban_plus_aspirin_still_fires_anticoag_nsaid_rule():
    """Regression: Aspirin is dual-classed antiplatelet + nsaid.
    ``anticoagulant-plus-nsaid`` catches this pair; the new doac-p2y12 rule
    does NOT displace it."""
    v = drug_safety.check_pair("Apixaban", "Aspirin")
    assert v.severity == "contraindicated"
    assert v.rule_id == "anticoagulant-plus-nsaid"


def test_apixaban_plus_atorvastatin_no_trigger():
    """Sanity: unrelated pair is allowed (no drug_safety rule fires)."""
    v = drug_safety.check_pair("Apixaban", "Atorvastatin")
    assert v.is_allowed


# --------------------------------------------------------------------------- #
# End-to-end via build_discharge_rx: DOAC on chronic + P2Y12 in
# discharge Rx → P2Y12 dropped.


@dataclass
class _StubMed:
    drug_name: str = ""
    drug_name_ja: str = ""
    dose: str = ""
    route: str = "PO"
    frequency: str = "daily"


@dataclass
class _StubPatient:
    patient_id: str = "pt-1334-test"
    baseline_chronic_medications: list = field(default_factory=list)
    current_medications: list = field(default_factory=list)
    chronic_conditions: list = field(default_factory=list)


def _make_stub_protocol_with_dapt() -> SimpleNamespace:
    """A cerebral_infarction-like protocol with a DAPT + DOAC-ish
    discharge_oral block: Apixaban + Aspirin + Clopidogrel emitted
    together (the exact pattern the finding flagged)."""
    return SimpleNamespace(
        disease_id="cerebral_infarction_test_fixture",
        drugs={
            "discharge_oral": {
                "us": [
                    {"drug": "Apixaban", "dose": "5mg", "route": "PO", "frequency": "bid"},
                    {"drug": "Aspirin", "dose": "81mg", "route": "PO", "frequency": "daily"},
                    {"drug": "Clopidogrel", "dose": "75mg", "route": "PO", "frequency": "daily"},
                ],
                "japan": [
                    {"drug": "Apixaban", "drug_ja": "アピキサバン", "dose": "5mg", "route": "PO", "frequency": "bid"},
                    {"drug": "Aspirin", "drug_ja": "アスピリン", "dose": "81mg", "route": "PO", "frequency": "daily"},
                    {
                        "drug": "Clopidogrel",
                        "drug_ja": "クロピドグレル",
                        "dose": "75mg",
                        "route": "PO",
                        "frequency": "daily",
                    },
                ],
            }
        },
    )


def test_discharge_rx_gate_drops_p2y12_when_doac_present():
    """Discharge Rx builder with a protocol authoring DOAC + Aspirin +
    Clopidogrel: the narrow doac-plus-p2y12 gate drops Clopidogrel
    (turning DOAC + Aspirin + P2Y12 triple into DOAC + Aspirin dual).
    Aspirin is intentionally NOT dropped — DOAC + Aspirin dual
    remains, because a broader anticoagulant-plus-nsaid gate would
    invalidate legitimate secondary-prevention combinations still
    used in the disease-YAML `continue_at_discharge` blocks
    (post-CVA / post-MI mixed cardioembolic + atherothrombotic
    coverage). See discharge_rx.py inline note for the follow-up
    trigger."""
    from clinosim.simulator.discharge_rx import build_discharge_rx

    patient = _StubPatient(baseline_chronic_medications=[], current_medications=[])
    protocol = _make_stub_protocol_with_dapt()

    from datetime import datetime

    rx = build_discharge_rx(
        patient=patient,
        protocol=protocol,
        disease_id="cerebral_infarction_test_fixture",
        prescriber_id="test-md",
        admission_time=datetime(2026, 6, 1, 8, 0),
        final_renal_function=0.9,
        country_key="us",
        encounter_id="enc-test-1334",
    )
    drug_names = {it["drug_name"] for it in rx.items}
    assert "Apixaban" in drug_names, f"expected Apixaban in items, got {drug_names}"
    assert "Aspirin" in drug_names, (
        f"Aspirin should still emit (broader gate deferred to future PR); items={drug_names}"
    )
    assert "Clopidogrel" not in drug_names, f"Clopidogrel should be dropped by doac-plus-p2y12 gate; items={drug_names}"


def test_discharge_rx_gate_allows_aspirin_plus_clopidogrel_without_doac():
    """Aspirin + Clopidogrel DAPT (no DOAC) has no rule against it →
    both should still emit. Regression against overly-aggressive gate."""
    from clinosim.simulator.discharge_rx import build_discharge_rx

    patient = _StubPatient()
    protocol = SimpleNamespace(
        disease_id="test_dapt_only",
        drugs={
            "discharge_oral": {
                "us": [
                    {"drug": "Aspirin", "dose": "81mg", "route": "PO", "frequency": "daily"},
                    {"drug": "Clopidogrel", "dose": "75mg", "route": "PO", "frequency": "daily"},
                ],
                "japan": [
                    {"drug": "Aspirin", "drug_ja": "アスピリン", "dose": "81mg", "route": "PO", "frequency": "daily"},
                    {
                        "drug": "Clopidogrel",
                        "drug_ja": "クロピドグレル",
                        "dose": "75mg",
                        "route": "PO",
                        "frequency": "daily",
                    },
                ],
            }
        },
    )
    from datetime import datetime

    rx = build_discharge_rx(
        patient=patient,
        protocol=protocol,
        disease_id="test_dapt_only",
        prescriber_id="test-md",
        admission_time=datetime(2026, 6, 1, 8, 0),
        final_renal_function=0.9,
        country_key="us",
        encounter_id="enc-test-dapt",
    )
    drug_names = {it["drug_name"] for it in rx.items}
    assert "Aspirin" in drug_names
    assert "Clopidogrel" in drug_names
