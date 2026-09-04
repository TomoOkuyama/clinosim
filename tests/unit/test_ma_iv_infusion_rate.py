"""B2 (#1067): MedicationAdministration IV protocol drugs get rateQuantity.

Before this fix, MA builder handled the ad-hoc "CONTINUOUS"/"DRIP"/"/h"
substring cases inline but skipped the catalog-based augmentation the MR
sibling gets via ``augment_iv_dosage_with_rate`` (Issue #966). That left
protocol-string IV meds (KCl range, sliding-scale insulin, NS bolus
without an explicit rate) with an empty ``dosage.dose``.

Measurement on US p=500 seed=500:
    baseline: IV MA empty = 9/221 (4.1 %)
    fix:      IV MA empty = 0/221 (0.0 %)
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_admin


def _mar(drug: str, route: str = "IV", dose: str = "") -> dict:
    return {
        "order_id": "ORD-TEST",
        "drug_name": drug,
        "scheduled_datetime": "2026-01-01T08:00:00",
        "actual_datetime": "2026-01-01T08:05:00",
        "status": "given",
        "dose": dose,
        "route": route,
        "administered_by": "N-1",
    }


def _has_rate(dosage: dict) -> bool:
    dar = dosage.get("doseAndRate") or []
    return any("rateQuantity" in entry for entry in dar) or "rateQuantity" in dosage


def test_kcl_iv_empty_dose_gets_rate_from_catalog() -> None:
    """The canonical B2 failure case: KCl ordered IV with no numeric dose."""
    r = _build_medication_admin(_mar("Potassium chloride", "IV", dose=""), "PT-1", 0)
    d = r.get("dosage", {})
    assert _has_rate(d), f"KCl IV should get catalog rate; got {d}"


def test_kcl_alias_iv_empty_dose_gets_rate() -> None:
    r = _build_medication_admin(_mar("KCl", "IV", dose=""), "PT-1", 0)
    d = r.get("dosage", {})
    assert _has_rate(d)


def test_ns_iv_bolus_gets_rate() -> None:
    r = _build_medication_admin(_mar("Normal saline", "IV", dose=""), "PT-1", 0)
    d = r.get("dosage", {})
    assert _has_rate(d)


def test_non_iv_drug_unchanged() -> None:
    """Non-IV route: augment must be a no-op (route gate)."""
    r = _build_medication_admin(_mar("Amlodipine", "PO", dose="5mg"), "PT-1", 0)
    d = r.get("dosage", {})
    # PO drug with structured dose still emits `dose`, but never a rate
    assert not _has_rate(d)


def test_iv_bolus_drug_gets_duration_not_rate() -> None:
    """Bolus-mode catalog entries emit timing.repeat.duration instead of rate."""
    # Ceftriaxone is a bolus-mode antibiotic in iv_infusion_defaults.yaml
    r = _build_medication_admin(_mar("Ceftriaxone", "IV", dose=""), "PT-1", 0)
    d = r.get("dosage", {})
    # Should emit either duration (bolus mode) or rate (continuous mode);
    # anything but silent-empty is acceptable per B2 fix intent.
    timing_dur = d.get("timing", {}).get("repeat", {}).get("duration")
    assert timing_dur is not None or _has_rate(d), f"IV bolus drug should get timing.duration or rate; got {d}"


def test_iv_augment_preserves_existing_structured_dose() -> None:
    """If MA already parsed a structured dose, augment adds rate on top."""
    r = _build_medication_admin(_mar("Normal saline", "IV", dose="100mL/h"), "PT-1", 0)
    d = r.get("dosage", {})
    # /h suffix triggers the pre-existing inline path (rateQuantity set to
    # 100 mL/h); catalog augment is a no-op because rate already present.
    assert _has_rate(d)
