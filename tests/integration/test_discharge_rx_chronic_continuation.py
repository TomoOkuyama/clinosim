"""Issue #417 段 1: continue_at_discharge mechanism for chronic-indicated
drug categories declared in disease YAML that are neither in the protocol
``discharge_oral`` block nor in the patient's pre-existing
``current_medications``.

Prior to this PR, ``cerebral_infarction`` (and 7 other diseases without
``discharge_oral``) silently dropped clinically necessary post-discharge
medications: secondary stroke prevention (DOAC or warfarin) + statin +
antihypertensive + antiplatelet. Those categories were declared under
``drugs.anticoagulation`` / ``drugs.antiplatelet`` / ``drugs.statin`` /
``drugs.antihypertensive`` in the disease YAML but had no reader in the
Python code — dead data (Issue #437).

This test cohort forces cerebral_infarction admissions with different
chronic-condition backgrounds:

  - **no prior chronic AC condition** — the discharge_rx must include an
    anticoagulant + statin + antihypertensive + antiplatelet (Aspirin
    always fires; Clopidogrel is Bernoulli 0.40).
  - **I48 (chronic AF) prior** — the discharge_rx must contain *exactly
    one* anticoagulant. The chronic transcription path (via
    ``patient.current_medications`` from ``chronic_medications.yaml``
    I48) already contributes one anticoagulant; the new
    ``continue_at_discharge`` loop must SKIP the anticoagulation
    category because ``anticoagulant`` is already covered by the chronic
    ICD (``covered_classes`` derivation from
    ``patient.chronic_conditions`` — see PR body for (a) vs (a')
    rationale).

Refs: #417 (段 1) / #432 (mutual exclusivity) / #437 (dead-code
activation) / #442 (drug_name string variance, out of scope) / #440
(段 2 resolved by PR #443).
"""

from __future__ import annotations

import pytest

from clinosim.simulator.engine import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig

# Distinct anticoagulant tokens observable in ``drug_name``. Case-insensitive
# substring match tolerates dose-appended variants ("warfarin" vs
# "Warfarin 3mg") without collapsing genuinely different drugs. Two DISTINCT
# tokens present in one patient's discharge_rx = the clinically dangerous
# 2-agent regimen that #432 fought to prevent.
_ANTICOAG_TOKENS = ("warfarin", "apixaban", "edoxaban", "rivaroxaban")


def _drug_names_lower(record) -> list[str]:
    if not record.discharge_prescription:
        return []
    return [
        str(item.get("drug_name", "") or "").lower()
        for item in record.discharge_prescription.items
        if item.get("drug_name")
    ]


def _distinct_anticoag_tokens(names_lower: list[str]) -> int:
    """Count DISTINCT anticoagulant tokens in the discharge_rx name list.

    'warfarin' + 'warfarin 3mg' → 1 (same drug, dose-string variance).
    'warfarin' + 'apixaban'     → 2 (dangerous 2-agent regimen).
    """
    return sum(1 for token in _ANTICOAG_TOKENS if any(token in name for name in names_lower))


@pytest.mark.integration
def test_cerebral_infarction_no_prior_ac_discharge_rx_includes_chronic_continuation():
    """cerebral_infarction admission without prior chronic AC condition.

    Post-fix expectation:
      - anticoagulant present in every patient's discharge_rx
        (JP: Edoxaban 0.8 / Warfarin 0.2, sum=1.0 → categorical always fires)
      - Aspirin (antiplatelet) present in every patient (implicit prob 1.0)
      - Atorvastatin (statin) present in every patient (implicit prob 1.0)
      - antihypertensive present (Amlodipine + Candesartan JP, both always)

    Pre-fix state: continue_at_discharge loop doesn't exist yet →
    discharge_rx omits ALL four categories → this test FAILS (0/N cohort
    hits for each). That FAIL is the required TDD signal.
    """
    cfg = SimulatorConfig(random_seed=901, country="JP")
    scenario = ForcedScenario(
        disease_id="cerebral_infarction",
        count=8,
        severity="moderate",
        patient_overrides={"chronic_conditions": []},
    )
    ds = run_forced(scenario, cfg)
    assert ds.patients, "run_forced produced no records"

    # Deceased patients get no discharge prescription — exclude from the
    # invariant. Their absence is orthogonal to this test's target.
    survivors = [r for r in ds.patients if not r.deceased]
    assert survivors, "cohort had no survivors — test is vacuous"

    per_patient_names = [_drug_names_lower(r) for r in survivors]

    anticoag_counts = [_distinct_anticoag_tokens(names) for names in per_patient_names]
    aspirin_seen = sum(1 for names in per_patient_names if any("アスピリン" in n or "aspirin" in n for n in names))
    statin_seen = sum(
        1 for names in per_patient_names if any("アトルバスタチン" in n or "atorvastatin" in n for n in names)
    )
    antihyp_seen = sum(
        1
        for names in per_patient_names
        if any(
            (t in n)
            for n in names
            for t in ("アムロジピン", "amlodipine", "カンデサルタン", "candesartan", "lisinopril")
        )
    )

    # Anticoag: JP categorical draw sums to 1.0 → every patient should receive
    # one. Assert full-cohort presence (not just ">=1").
    assert all(c >= 1 for c in anticoag_counts), (
        f"anticoagulant absent in some patients — continue_at_discharge loop "
        f"regressed. anticoag_counts={anticoag_counts}. "
        f"names_per_patient={per_patient_names}"
    )
    # Antiplatelet, statin, antihypertensive: independent-always → every patient.
    assert aspirin_seen == len(survivors), f"Aspirin absent in {len(survivors) - aspirin_seen} patients"
    assert statin_seen == len(survivors), f"Atorvastatin absent in {len(survivors) - statin_seen} patients"
    assert antihyp_seen == len(survivors), f"antihypertensive absent in {len(survivors) - antihyp_seen} patients"

    # No patient may have 2 different anticoagulant tokens (would be the
    # #432 dangerous 2-agent regimen re-emerging).
    dangerous = [(i, c) for i, c in enumerate(anticoag_counts) if c >= 2]
    assert not dangerous, (
        f"{len(dangerous)} patient(s) received 2+ distinct anticoagulant tokens. anticoag_counts={anticoag_counts}"
    )


@pytest.mark.integration
def test_cerebral_infarction_with_chronic_af_no_cross_source_anticoag_duplication():
    """cerebral_infarction admission WITH prior I48 (chronic AF).

    The chronic transcription (path 2) MUST contribute one anticoagulant
    (from chronic_medications.yaml I48 exclusive draw). The new
    continue_at_discharge loop (path 3) MUST detect that ``anticoagulant``
    class is already covered via patient.chronic_conditions → skip the
    ``drugs.anticoagulation`` category. Result: exactly 1 anticoagulant
    token per patient.

    Pre-fix state: path 3 doesn't exist. Path 2 gives 1 anticoag from
    chronic. Test PASSES (regression guard for post-fix implementation
    forgetting the covered_classes derivation).
    """
    cfg = SimulatorConfig(random_seed=902, country="US")
    scenario = ForcedScenario(
        disease_id="cerebral_infarction",
        count=6,
        severity="moderate",
        patient_overrides={"chronic_conditions": ["I48"]},
    )
    ds = run_forced(scenario, cfg)
    assert ds.patients
    survivors = [r for r in ds.patients if not r.deceased]
    assert survivors, "cohort had no survivors — test is vacuous"

    per_patient_names = [_drug_names_lower(r) for r in survivors]
    counts = [_distinct_anticoag_tokens(names) for names in per_patient_names]

    bad = [(i, c) for i, c in enumerate(counts) if c != 1]
    assert not bad, (
        f"cross-source anticoagulant count != 1 in {len(bad)}/{len(counts)} "
        f"patients. counts={counts}. names_per_patient={per_patient_names}"
    )
