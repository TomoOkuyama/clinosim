"""Issue #1318 — PRN rescue inhaler modelled as chronic monthly refill.

Pre-fix the outpatient prescription-renewal loop emitted a fresh
community-category MR for every entry in ``patient.current_medications``
at every visit. Salbutamol (SABA rescue inhaler) is chronic-med-YAML
tagged ``frequency: "prn"`` — clinically a real Salbutamol pMDI is a
1-4/year refill, not per-monthly-followup renewal. Random-sample
review flagged top-user COPD patients with 14 Salbutamol MRs/year
(one per followup).

The fix skips ``frequency == "prn"`` meds from the outpatient renewal
loop. PRN meds remain on ``patient.current_medications`` and continue
to surface via inpatient admission home-med orders + discharge Rx +
narrative (~1-4 MRs/year cohort-wide, matching real refill cadence).
"""

from __future__ import annotations

from dataclasses import dataclass

from clinosim.types.encounter import PrescriptionRecord


@dataclass
class _StubMed:
    drug_name: str
    drug_name_ja: str = ""
    dose: str = ""
    route: str = ""
    frequency: str = ""


def _run_outpatient_renewal(current_medications: list, in_pregnancy: bool = False) -> PrescriptionRecord:
    """Minimal repro of the outpatient renewal loop's items-construction
    to test the PRN filter in isolation from the surrounding encounter
    machinery."""

    def _is_prn(med) -> bool:
        return str(getattr(med, "frequency", "") or "").strip().lower() == "prn"

    items = [
        {
            "drug_name": m.drug_name,
            "drug_name_ja": m.drug_name_ja,
            "dose": m.dose,
            "route": m.route,
            "frequency": m.frequency,
            "duration_days": 28,
        }
        for m in current_medications
        if not _is_prn(m)
    ]
    return PrescriptionRecord(
        prescription_id="RX-TEST-OPD",
        prescriber_id="test-md",
        items=items,
    )


def test_prn_salbutamol_dropped_from_outpatient_renewal():
    meds = [
        _StubMed("Salbutamol", "サルブタモール", "100mcg", "INH", "prn"),
        _StubMed("Tiotropium", "チオトロピウム", "18mcg", "INH", "daily"),
    ]
    rx = _run_outpatient_renewal(meds)
    names = {it["drug_name"] for it in rx.items}
    assert "Salbutamol" not in names, "PRN Salbutamol must be dropped from outpatient renewal"
    assert "Tiotropium" in names, "Non-PRN Tiotropium must still emit"


def test_prn_case_insensitive():
    """``frequency: "PRN"`` uppercase should also be filtered."""
    meds = [_StubMed("Nitroglycerin_SL", frequency="PRN")]
    rx = _run_outpatient_renewal(meds)
    assert rx.items == []


def test_scheduled_frequencies_never_dropped():
    for freq in ("daily", "bid", "tid", "qid", "weekly", "monthly"):
        meds = [_StubMed(f"Drug_{freq}", frequency=freq)]
        rx = _run_outpatient_renewal(meds)
        assert len(rx.items) == 1, f"{freq}-frequency drug must not be dropped"


def test_empty_frequency_never_dropped():
    """A drug with empty frequency (unknown scheduling) must NOT be treated
    as PRN. Missing metadata should not silently suppress emit."""
    meds = [_StubMed("Unknown_freq_drug", frequency="")]
    rx = _run_outpatient_renewal(meds)
    assert len(rx.items) == 1


def test_salbutamol_yaml_entry_carries_prn_frequency():
    """Regression against silent YAML edits that would revert Salbutamol
    to a scheduled frequency and defeat the filter."""
    from clinosim.locale.loader import load_chronic_medications

    data = load_chronic_medications()
    # Salbutamol appears in J44 (COPD) chronic med block; may also appear in J45 (asthma).
    j44 = data.get("J44", {})
    meds = j44.get("medications", [])
    salbutamol_entries = [m for m in meds if m.get("drug") == "Salbutamol"]
    assert salbutamol_entries, "J44 chronic block must list Salbutamol"
    for m in salbutamol_entries:
        assert m.get("frequency", "").lower() == "prn", (
            f"J44 Salbutamol entry must have frequency=prn, got {m.get('frequency')!r}"
        )
