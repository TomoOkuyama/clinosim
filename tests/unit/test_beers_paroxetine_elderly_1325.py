"""Issue #1325 — AGS Beers Criteria 2023: Paroxetine is on the "avoid"
list for adults age ≥ 65 (high anticholinergic burden → cognitive
impairment; orthostatic hypotension → fall risk). The F41.1 chronic-med
sampler previously drew Paroxetine at 0.10 probability regardless of
patient age.

Fix: added ``age_max: 64`` on the Paroxetine entry in
``chronic_medications.yaml``, and extended
``select_with_exclusive_classes`` (``modules/_shared.py``) with
optional ``patient_age`` filtering. Elderly patients still receive
SSRI treatment via the geriatric-first-line drugs (Sertraline,
Escitalopram); only Paroxetine drops out.
"""

from __future__ import annotations

import numpy as np

from clinosim.modules._shared import select_with_exclusive_classes


def _f41_specs():
    return [
        {"drug": "Escitalopram", "drug_class": "ssri", "probability": 0.28},
        {"drug": "Sertraline", "drug_class": "ssri", "probability": 0.22},
        {"drug": "Paroxetine", "drug_class": "ssri", "probability": 0.10, "age_max": 64},
        {"drug": "Venlafaxine", "drug_class": "snri", "probability": 0.15},
        {"drug": "Duloxetine", "drug_class": "snri", "probability": 0.10},
    ]


def test_paroxetine_never_picked_for_age_70():
    # Sweep 500 different seeds; age 70 must never yield Paroxetine.
    for seed in range(500):
        picked = select_with_exclusive_classes(
            _f41_specs(),
            {"ssri", "snri"},
            np.random.default_rng(seed),
            patient_age=70,
        )
        names = {d["drug"] for d in picked}
        assert "Paroxetine" not in names, f"seed={seed} picked Paroxetine at age 70"


def test_paroxetine_still_picked_for_age_40():
    # Age 40 is below the ceiling — Paroxetine remains in the eligible
    # ssri pool. A large sweep should pick it at least a few times
    # (0.10 probability × 500 seeds ≈ 50 expected).
    hits = 0
    for seed in range(500):
        picked = select_with_exclusive_classes(
            _f41_specs(),
            {"ssri", "snri"},
            np.random.default_rng(seed),
            patient_age=40,
        )
        if any(d["drug"] == "Paroxetine" for d in picked):
            hits += 1
    assert hits > 20, f"Paroxetine picked only {hits}/500 at age 40 — expected ≈ 50"


def test_paroxetine_picked_at_age_64_boundary():
    # Boundary: age_max=64 means age 64 is INCLUSIVE (still eligible).
    hits = 0
    for seed in range(500):
        picked = select_with_exclusive_classes(
            _f41_specs(),
            {"ssri", "snri"},
            np.random.default_rng(seed),
            patient_age=64,
        )
        if any(d["drug"] == "Paroxetine" for d in picked):
            hits += 1
    assert hits > 20, f"Paroxetine picked only {hits}/500 at age 64 — expected ≈ 50 (boundary inclusive)"


def test_paroxetine_dropped_at_age_65_boundary():
    # Boundary: age 65 is above the ceiling — Paroxetine dropped.
    for seed in range(500):
        picked = select_with_exclusive_classes(
            _f41_specs(),
            {"ssri", "snri"},
            np.random.default_rng(seed),
            patient_age=65,
        )
        assert "Paroxetine" not in {d["drug"] for d in picked}


def test_elderly_still_receive_geriatric_first_line_ssri():
    # Elderly patients still get Sertraline or Escitalopram (safe SSRIs);
    # the fix only removes Paroxetine, not the entire ssri class.
    ssri_hits = 0
    for seed in range(500):
        picked = select_with_exclusive_classes(
            _f41_specs(),
            {"ssri", "snri"},
            np.random.default_rng(seed),
            patient_age=80,
        )
        names = {d["drug"] for d in picked}
        if names & {"Sertraline", "Escitalopram"}:
            ssri_hits += 1
    # 0.28 + 0.22 = 0.50 residual ssri probability after Paroxetine drop
    # (Paroxetine's 0.10 is now in "no ssri" branch).
    assert ssri_hits > 200, f"only {ssri_hits}/500 elderly patients received safe SSRI — expected ≈ 250"


def test_no_age_parameter_preserves_pre_1325_behavior():
    # Backwards compat: existing callers that don't pass patient_age
    # see the pre-1325 behavior (age filter no-op).
    hits = 0
    for seed in range(500):
        picked = select_with_exclusive_classes(
            _f41_specs(),
            {"ssri", "snri"},
            np.random.default_rng(seed),
        )
        if any(d["drug"] == "Paroxetine" for d in picked):
            hits += 1
    assert hits > 20, f"Paroxetine picked only {hits}/500 with no age gate — regression"
