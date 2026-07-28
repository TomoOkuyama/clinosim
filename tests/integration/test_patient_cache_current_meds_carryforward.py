"""A' Phase 1 (Issue #440) integration gate: engine.py must sync
patient_cache.current_medications after ``_deactivate_to_layer1``.

Observable behavior under test (engine-layer, not helper-layer):

    "For any patient hospitalized twice where an anticoagulant was NEWLY
    STARTED during their first admission (i.e., not present in the
    pre-admission ``patient.current_medications`` but written into the
    first discharge_prescription), their SECOND admission's home
    medication orders must contain the same anticoagulant."

This is the E2E gate that survives a regression where ``engine.py`` stops
passing ``patient_cache=`` to ``_deactivate_to_layer1`` — the helper alone
cannot sync a cache it does not know about, so the second admission's
``_generate_home_medication_orders`` will emit the pre-admission chronic
list only and the anticoag will silently disappear.

Cohort: ``p=500 seed=42 country=US`` (fixed). Scout at implementation time
found POP-000257: admission #1 = atrial_fibrillation_rvr (2025-02)
discharges with Apixaban newly prescribed; admission #2 = acute_mi
(2025-09) six months later. Master (pre-A') drops Apixaban from admission
#2 home medication orders.

Candidate-extraction discipline (监督 requirement):
* The candidate must satisfy **the drug was newly started during
  admission #1** (= not present in the patient's home medications AT
  admission #1 time). Without this, a chronic anticoag patient's
  continuation via the existing chronic-transcribe path in
  ``_build_discharge_rx`` would masquerade as A' working and mask the
  actual regression.
* "Newly-started at admission #1" is detected via ``first``'s own
  ``_generate_home_medication_orders`` output (``Order.clinical_intent``
  starts with ``"Home medication"``). ``Order`` objects are freshly
  constructed per encounter, so they are a stable snapshot of the
  admission-time state — unlike ``first.patient.current_medications``
  which is a live reference to the shared ``patient_cache[pid]`` profile
  and reflects the *post-A'-sync* state (would falsely include the newly
  started drug and disqualify the patient).
* Candidate count zero → ``pytest.fail`` (never skip). If the cohort ever
  loses this fixture (data drift, disease-YAML change), we want a loud
  failure asking for maintenance, not a green silent test.
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig
from clinosim.types.output import CIFPatientRecord

ANTICOAG_TERMS = ("warfarin", "apixaban", "rivaroxaban", "edoxaban", "dabigatran")


def _has_anticoag(names: list[str]) -> bool:
    return any(any(term in n.lower() for term in ANTICOAG_TERMS) for n in names)


def _anticoag_hits(names: list[str]) -> list[str]:
    return [n for n in names if any(term in n.lower() for term in ANTICOAG_TERMS)]


def _inpatients_sorted(recs: list[CIFPatientRecord]) -> list[CIFPatientRecord]:
    """Inpatient records for one patient, sorted by admission_datetime."""
    return sorted(
        [r for r in recs if r.encounters and r.encounters[0].encounter_type.value == "inpatient"],
        key=lambda r: r.encounters[0].admission_datetime,
    )


def _find_carryforward_candidates(
    patients: list[CIFPatientRecord],
) -> list[tuple[str, CIFPatientRecord, CIFPatientRecord, list[str]]]:
    """Extract patients matching the A' invariant precondition.

    A candidate is (pid, first_admission, second_admission, newly_started_anticoags)
    where:
      - patient has 2+ inpatient admissions
      - 1st admission's discharge_prescription contains anticoag X
      - X is NOT in ``first``'s home_medication orders
        (= X was newly started during admission #1, not chronic-inherited)

    Anti-flake note: we deliberately DO NOT compare against
    ``first.patient.current_medications`` — that is a live reference to
    the cached PatientProfile, which A' now mutates in-place. Using it
    would make impl-after runs falsely disqualify the candidate.
    """
    by_pid: dict[str, list[CIFPatientRecord]] = {}
    for r in patients:
        by_pid.setdefault(r.patient.patient_id, []).append(r)

    candidates: list[tuple[str, CIFPatientRecord, CIFPatientRecord, list[str]]] = []
    for pid, recs in by_pid.items():
        inpts = _inpatients_sorted(recs)
        if len(inpts) < 2:
            continue
        first, second = inpts[0], inpts[1]
        if not (first.discharge_prescription and first.discharge_prescription.items):
            continue

        dc_drugs = [str(item.get("drug_name", "") or "") for item in first.discharge_prescription.items]
        dc_anticoags = _anticoag_hits(dc_drugs)
        if not dc_anticoags:
            continue

        # Admission-time snapshot via Order objects (record-owned, not shared).
        first_home_meds = _home_med_display_names(first)

        # Newly started = anticoag in dc_drugs whose substring anticoag class
        # is NOT already in first_home_meds.
        def _class_of(name: str) -> str | None:
            low = name.lower()
            for term in ANTICOAG_TERMS:
                if term in low:
                    return term
            return None

        home_med_classes = {c for c in (_class_of(m) for m in first_home_meds) if c}
        newly_started = [drug for drug in dc_anticoags if (_class_of(drug) not in home_med_classes)]
        if not newly_started:
            continue

        candidates.append((pid, first, second, newly_started))

    return candidates


def _home_med_display_names(record: CIFPatientRecord) -> list[str]:
    """Home medication order display_names for an admission (Order.clinical_intent
    prefix 'Home medication')."""
    return [
        o.display_name
        for o in record.orders
        if _order_type_value(o) == "medication" and (o.clinical_intent or "").startswith("Home medication")
    ]


def _order_type_value(o: Any) -> str:
    ot = getattr(o, "order_type", None)
    if ot is None:
        return ""
    if hasattr(ot, "value"):
        return str(ot.value)
    return str(ot)


@pytest.mark.integration
def test_anticoag_from_admission1_carries_forward_to_admission2_home_meds():
    """Engine-layer gate for A' Phase 1 (Issue #440)."""
    # Fixed cohort scouted at implementation time to reliably contain the
    # POP-000257-style fixture. Do NOT tighten seed/config without also
    # re-verifying the candidate set exists.
    config = SimulatorConfig(
        random_seed=42,
        catchment_population=500,
        country="US",
        time_range=("2025-01", "2026-01"),
    )
    ds = run_beta(config)

    candidates = _find_carryforward_candidates(ds.patients)

    if not candidates:
        pytest.fail(
            "test cohort no longer contains any patient with (2+ inpatient "
            "admissions AND anticoag newly-started at admission #1). The "
            "A' invariant premise is lost — do NOT skip. Either update the "
            "seed/config to a cohort that reliably contains such a patient, "
            "or investigate whether a regression removed anticoag from "
            "disease discharge_oral blocks (PE / DVT / afib / hemorrhagic "
            "stroke)."
        )

    failures: list[tuple[str, list[str], list[str]]] = []
    for pid, _first, second, newly_started_anticoags in candidates:
        second_home = _home_med_display_names(second)
        if not _has_anticoag(second_home):
            failures.append((pid, second_home, newly_started_anticoags))

    assert not failures, (
        f"A' invariant violation: {len(failures)}/{len(candidates)} patients "
        f"had an anticoagulant newly-started at admission #1 that did NOT "
        f"appear as a home medication order at admission #2. This is the "
        f"engine.py cache-sync gate — engine must pass patient_cache= to "
        f"_deactivate_to_layer1 so the cached PatientProfile stays consistent "
        f"with person.current_medications across encounters.\n"
        f"Failure samples (up to 5):\n"
        + "\n".join(
            f"  pid={pid}  newly_started_at_adm1={anticoags}  adm2_home_meds={home}"
            for pid, home, anticoags in failures[:5]
        )
    )
