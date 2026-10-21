"""Cycle 2 M3 — sliding scale insulin must not appear on outpatient
chronic home medication lists.

Sliding scale insulin is an INPATIENT-ONLY PRN protocol for DKA / HHS /
peri-op hyperglycemia; ADA Standards of Care in Diabetes 2024 §9
explicitly rejects sliding-scale for ambulatory chronic T2DM care. The
DKA protocol (`clinosim/modules/disease/reference_data/diabetic_ketoacidosis.yaml`)
legitimately uses sliding scale during admission, but the home-medication
sampler must not activate it.

Cycle 2 audit (US p=2000 seed=42) found 29 of 160 T2DM patients across
1254 encounter CIFs carrying `Sliding scale insulin` on their outpatient
`current_medications` list. Root cause: `chronic_medications.yaml::E11.9`
carried a `probability: 0.4` entry for Sliding scale, so
`_derive_home_medications` sampled it independently per activation.
"""

from __future__ import annotations

from dataclasses import dataclass

from clinosim.modules.patient.activator import _derive_home_medications


@dataclass
class _Cond:
    code: str


def test_e11_chronic_never_activates_sliding_scale_insulin() -> None:
    """Across a sweep of 500 T2DM (E11.9) patients, the home-medication
    sampler must never return Sliding scale insulin on either locale."""
    for country in ("US", "JP"):
        for i in range(500):
            pid = f"pt-m3-sweep-{country}-{i:06d}"
            meds = _derive_home_medications(
                [_Cond(code="E11.9")],
                country=country,
                patient_id=pid,
            )
            hits = [m.drug_name for m in meds if "liding scale" in (m.drug_name or "")]
            assert not hits, f"pt {pid} ({country}) activated Sliding scale insulin on chronic path: {hits}"


def test_e11_chronic_still_activates_metformin_at_expected_rate() -> None:
    """Removing the Sliding scale entry must not disturb Metformin
    activation — Metformin is the first chronic entry in the E11.9 block
    with no `probability` field (defaults to 1.0, always active)."""
    met_hits = 0
    sweep = 300
    for i in range(sweep):
        pid = f"pt-m3-met-{i:06d}"
        meds = _derive_home_medications(
            [_Cond(code="E11.9")],
            country="US",
            patient_id=pid,
        )
        if any("Metformin" in (m.drug_name or "") for m in meds):
            met_hits += 1
    assert met_hits >= sweep * 0.9, f"Metformin dropped unexpectedly: {met_hits}/{sweep} T2DM patients"
