"""Issue #1329 — Capecitabine + FOLFOX (double 5-FU) chronic-med mutex.

A C18 chronic-carrier who is Bernoulli-sampled into an active FOLFOX
regimen (from ``chemo_regimens.yaml::by_cancer``) MUST NOT ALSO receive
Capecitabine as an oral chronic home medication — Capecitabine is a
5-FU pro-drug, so combining oral Capecitabine with IV 5-FU (in FOLFOX)
doubles the fluoropyrimidine exposure (severe mucositis, hand-foot
syndrome, myelosuppression, cardiotoxicity).

Mechanism: ``_derive_home_medications`` queries the same
``chemotherapy_regimen_seed(patient_id, cancer_code)`` sub-RNG that
``_chemo_cycle_events`` consumes to decide whether the patient carries
an active regimen, then zeroes the ``probability`` of any chronic med
whose ``drug_class`` appears in the regimen's ``contains_drug_classes``.
The zeroed probability is RNG-preserving inside
``select_with_exclusive_classes`` — the same number of ``rng.random()``
calls fire regardless.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from clinosim.locale.loader import load_chemo_regimens
from clinosim.modules.patient.activator import _derive_home_medications
from clinosim.modules.population.engine import pick_active_chemo_regimen
from clinosim.seeding import chemotherapy_regimen_seed


@dataclass
class _Cond:
    code: str


def _folfox_positive_patient_ids(cancer_code: str, n_sweep: int) -> list[str]:
    """Sweep patient ids and return those whose per-code sub-RNG picks FOLFOX
    (or any regimen containing fluoropyrimidine) for the given cancer code."""
    data = load_chemo_regimens()
    regimens = data.get("regimens") or {}
    by_cancer = data.get("by_cancer") or {}
    hits: list[str] = []
    for i in range(n_sweep):
        pid = f"pt-1329-sweep-{i:06d}"
        chemo_rng = np.random.default_rng(chemotherapy_regimen_seed(pid, cancer_code))
        picked = pick_active_chemo_regimen(chemo_rng, regimens, by_cancer, cancer_code)
        if picked is None:
            continue
        _, regimen = picked
        classes = set(regimen.get("contains_drug_classes") or ())
        if "fluoropyrimidine" in classes:
            hits.append(pid)
    return hits


def test_folfox_active_c18_patients_never_get_capecitabine():
    """For C18 patients on active FOLFOX (fluoropyrimidine-containing IV
    regimen), Capecitabine chronic MR MUST be dropped from the sampler."""
    folfox_pids = _folfox_positive_patient_ids("C18", n_sweep=500)
    assert len(folfox_pids) >= 20, (
        f"expected >=20 FOLFOX-positive C18 pts in 500 sweep (probability=0.25), got {len(folfox_pids)}"
    )
    for pid in folfox_pids:
        meds = _derive_home_medications(
            [_Cond(code="C18")],
            country="US",
            patient_id=pid,
        )
        cape_hits = [m for m in meds if "Capecitabine" in m.drug_name]
        assert not cape_hits, (
            f"pt {pid} on active FOLFOX still received Capecitabine chronic MR: {[m.drug_name for m in cape_hits]}"
        )


def test_no_active_regimen_c18_patients_still_get_capecitabine_at_expected_rate():
    """C18 patients whose sub-RNG picks the surveillance-only residual
    (no active regimen) fall through the mutex gate and continue to
    receive Capecitabine at the yaml probability (0.5). Assert the
    surviving Capecitabine hit rate is close to the intersection of
    ``P(surveillance) × P(Capecitabine)`` — pre-mutex was 0.5 flat,
    post-mutex is (1 - 0.25) × 0.5 = 0.375 in expectation."""
    n_sweep = 500
    n_cape = 0
    for i in range(n_sweep):
        pid = f"pt-1329-rate-{i:06d}"
        meds = _derive_home_medications(
            [_Cond(code="C18")],
            country="US",
            patient_id=pid,
        )
        if any("Capecitabine" in m.drug_name for m in meds):
            n_cape += 1
    # Expected: 0.5 × (1 - 0.25) = 0.375 ≈ 188 / 500. Tolerance ±20 %
    # to keep the smoke test stable across CI runs. Regression floor:
    # if the mutex overshoots and drops every Capecitabine, this fails.
    expected = n_sweep * 0.5 * (1 - 0.25)
    lo, hi = int(expected * 0.75), int(expected * 1.25)
    assert lo <= n_cape <= hi, (
        f"Capecitabine hit rate {n_cape}/{n_sweep} outside {lo}-{hi} window "
        f"(pre-mutex was ~0.5*{n_sweep}={n_sweep // 2}; expected ~{int(expected)})"
    )


def test_pick_active_chemo_regimen_returns_shared_regimen_dict():
    """Both call sites (``_chemo_cycle_events`` and
    ``_derive_home_medications``) query the helper on the same
    ``chemotherapy_regimen_seed(patient_id, cancer_code)`` sub-RNG, so
    they observe identical regimen assignments. Sanity-check the
    round trip on one known FOLFOX-positive patient id."""
    data = load_chemo_regimens()
    regimens = data.get("regimens") or {}
    by_cancer = data.get("by_cancer") or {}

    # Reuse a known-positive id from the sweep helper (deterministic).
    folfox_pids = _folfox_positive_patient_ids("C18", n_sweep=100)
    assert folfox_pids, "sweep found no FOLFOX-positive ids (seed regression?)"
    pid = folfox_pids[0]

    rng_a = np.random.default_rng(chemotherapy_regimen_seed(pid, "C18"))
    rng_b = np.random.default_rng(chemotherapy_regimen_seed(pid, "C18"))
    picked_a = pick_active_chemo_regimen(rng_a, regimens, by_cancer, "C18")
    picked_b = pick_active_chemo_regimen(rng_b, regimens, by_cancer, "C18")
    assert picked_a is not None and picked_b is not None
    assert picked_a[0] == picked_b[0] == "FOLFOX"
    assert "fluoropyrimidine" in (picked_a[1].get("contains_drug_classes") or ())
