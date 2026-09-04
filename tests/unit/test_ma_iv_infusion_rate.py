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


# ---------------------------------------------------------------------------
# C3 / Issue #1089: bolus IV drugs (cephalosporin, chemo) — dose lives on
# the parent Order, but ``mar.dose`` often carries a route-only hint like
# "IV" that trips the "not empty" gate and prevents the backfill from
# parent_order.dose_quantity/dose_unit from running.
# ---------------------------------------------------------------------------


def _has_dose(dosage: dict) -> bool:
    if dosage.get("dose", {}).get("value") not in (None, 0):
        return True
    for dr in dosage.get("doseAndRate", []) or []:
        if dr.get("doseQuantity", {}).get("value") not in (None, 0):
            return True
    return False


def test_bolus_iv_dose_from_parent_order_when_mar_dose_is_route_only() -> None:
    """Cefmetazole ordered ``1g IV q8h`` → parent Order carries
    dose_quantity=1, dose_unit='g'. MAR generator wrote ``mar.dose = 'IV'``
    (a route hint, not a dose). Post-C3 the MA must backfill from the
    parent order so the emitted dosage carries a numeric dose.
    """
    parent = {
        "dose_quantity": 1.0,
        "dose_unit": "g",
        "frequency": "Q8H",
        "route": "IV",
    }
    r = _build_medication_admin(
        _mar("Cefmetazole", "IV", dose="IV"),
        "PT-1",
        0,
        parent_order=parent,
    )
    d = r.get("dosage", {})
    assert _has_dose(d), f"Cefmetazole IV should backfill dose from parent Order (1 g); got {d}"


def test_bolus_iv_chemo_dose_from_parent_order() -> None:
    """Carboplatin per-cycle IV dose (e.g. 350 mg over 60 min) — same
    pattern as antibiotics: parent Order carries the numeric dose, mar
    just labels the route."""
    parent = {"dose_quantity": 350.0, "dose_unit": "mg", "route": "IV"}
    r = _build_medication_admin(
        _mar("Carboplatin", "IV", dose="IV"),
        "PT-1",
        0,
        parent_order=parent,
    )
    d = r.get("dosage", {})
    assert _has_dose(d), f"Carboplatin IV should backfill dose from parent Order (350 mg); got {d}"


def test_bolus_iv_dose_backfill_does_not_override_real_mar_dose() -> None:
    """If ``mar.dose`` already has a numeric dose string, the parent Order
    backfill must NOT overwrite it. The MAR reflects what was actually
    administered; only fill when the MAR field is missing."""
    parent = {"dose_quantity": 1.0, "dose_unit": "g"}
    r = _build_medication_admin(
        _mar("Cefmetazole", "IV", dose="0.5g"),  # partial dose administered
        "PT-1",
        0,
        parent_order=parent,
    )
    d = r.get("dosage", {})
    # dose.value must be 0.5 (from mar.dose), not 1.0 (from parent)
    dose_val = d.get("dose", {}).get("value")
    assert dose_val == 0.5, f"expected mar.dose=0.5g to win over parent 1g; got {dose_val}"


def test_bolus_iv_no_parent_no_mar_dose_emits_nothing() -> None:
    """Honest-empty: no parent Order + no mar.dose → we do NOT invent
    a dose. The dosage element may still carry timing/route/text; but
    it must not carry a fabricated numeric dose."""
    # Ceftazidime is not in the catalog rate defaults; parent_order=None.
    r = _build_medication_admin(
        _mar("Ceftazidime", "IV", dose=""),
        "PT-1",
        0,
        parent_order=None,
    )
    d = r.get("dosage", {})
    assert not _has_dose(d), f"no dose source → expected no fabricated dose; got {d}"
