"""META #1792 Phase 1b — coverage audit for the Phase 4 escalation
drugs that triggered #1765.

Before Phase 1b, 11 drugs emitted by the longitudinal escalation /
GLP-1 pharmacotherapy / F10 chronic-med paths carried no RxCUI in
rxnorm.yaml, driving the 26% MedicationRequest-missing-RxNorm gap:

  SGLT2 inhibitors:        Empagliflozin, Dapagliflozin
  GLP-1 (+ GIP) agonists:  Semaglutide, Liraglutide, Tirzepatide
  Statin (high-intensity): Rosuvastatin
  Cholesterol absorption:  Ezetimibe
  Alcohol use disorder:    Naltrexone, Acamprosate
  Antihypertensive:        Hydrochlorothiazide, Spironolactone

Phase 1b adds these to rxnorm.yaml (verified via NLM RxNav
``/REST/rxcui/<cui>/properties.json`` → tty=IN) AND threads them
through drugs.yaml so downstream FHIR emit can resolve them.

The tests here lock in the coverage so a Phase 2+ migration can't
quietly drop any of these mappings.
"""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import all_drug_ids, resolve_drug
from clinosim.codes.loader import _load_system

pytestmark = pytest.mark.unit


_PHASE_4_DRUGS: tuple[tuple[str, str, str], ...] = (
    ("empagliflozin", "Empagliflozin", "1545653"),
    ("dapagliflozin", "Dapagliflozin", "1488564"),
    ("semaglutide", "Semaglutide", "1991302"),
    ("liraglutide", "Liraglutide", "475968"),
    ("tirzepatide", "Tirzepatide", "2601723"),
    ("rosuvastatin", "Rosuvastatin", "301542"),
    ("ezetimibe", "Ezetimibe", "341248"),
    ("naltrexone", "Naltrexone", "7243"),
    ("acamprosate", "Acamprosate", "82819"),
    ("hydrochlorothiazide", "Hydrochlorothiazide", "5487"),
    ("spironolactone", "Spironolactone", "9997"),
)


@pytest.mark.parametrize("drug_id, display_en, rxcui", _PHASE_4_DRUGS)
def test_phase_4_drug_registered_in_drugs_catalog(drug_id: str, display_en: str, rxcui: str):
    """Every Phase 4 escalation drug must have a drugs.yaml entry
    with the expected display + RxCUI pointer."""
    rec = resolve_drug(drug_id)
    assert rec.names["en"] == display_en
    assert rec.codes.get("rxnorm") == rxcui, (
        f"{drug_id}: expected RxCUI {rxcui} per NLM RxNav verification; got {rec.codes.get('rxnorm')!r}"
    )


@pytest.mark.parametrize("drug_id, display_en, rxcui", _PHASE_4_DRUGS)
def test_phase_4_rxcui_resolves_against_rxnorm_yaml(drug_id: str, display_en: str, rxcui: str):
    """The RxCUI pointer must exist in rxnorm.yaml. #1765's downstream
    emitter resolves ``MedicationRequest.medicationCodeableConcept.coding``
    via this lookup — a dangling pointer would re-open the gap."""
    rxnorm_system = _load_system("rxnorm")
    assert rxnorm_system is not None
    assert rxcui in rxnorm_system.codes, (
        f"{drug_id}: RxCUI {rxcui} must be in rxnorm.yaml for the FHIR emit to resolve a canonical coding"
    )


def test_phase_4_coverage_is_complete():
    """Every drug in the Phase 4 set must have a drug_id in the catalog.
    This is the single invariant that keeps #1765's gap closed as the
    simulator evolves."""
    missing = [d for d, _, _ in _PHASE_4_DRUGS if d not in all_drug_ids()]
    assert not missing, f"Phase 4 drug_ids missing from drugs.yaml: {missing}"


def test_catalog_covers_every_rxnorm_entry():
    """Phase 1b mirror invariant: every RxCUI in rxnorm.yaml must be
    reachable from drugs.yaml by at least one drug_id. A Phase 2
    migration that trips this test has dropped a drug mapping."""
    rxnorm_system = _load_system("rxnorm")
    assert rxnorm_system is not None
    catalog_rxcuis = {resolve_drug(d).codes.get("rxnorm") for d in all_drug_ids()}
    catalog_rxcuis.discard(None)
    orphan_rxcuis = set(rxnorm_system.codes.keys()) - catalog_rxcuis
    assert not orphan_rxcuis, (
        f"{len(orphan_rxcuis)} RxCUIs in rxnorm.yaml have no drug_id in "
        f"drugs.yaml (sample): {sorted(orphan_rxcuis)[:5]}"
    )
