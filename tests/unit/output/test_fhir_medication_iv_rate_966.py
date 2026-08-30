"""Issue #966 — IV MedicationRequests carry rateQuantity or timing.duration.

Pre-fix: 421/421 IV-route MedicationRequests emitted by PR #920 shipped
without any infusion rate (or bolus duration) — leaving downstream drug-
safety alerts (KCl > 10 mEq/h, vancomycin > 10 mg/min) and nursing-side
administration reconstruction impossible to derive.

Post-fix: ``augment_iv_dosage_with_rate`` (called from both
``build_dosage_instruction`` and ``_build_discharge_medication_request``)
looks up per-drug defaults from ``iv_infusion_defaults.yaml``:
  - continuous drips → ``doseAndRate.rateQuantity``
  - intermittent bolus → ``timing.repeat.duration`` + ``durationUnit=min``
  - IV push (< 5 min) → intentional no-op (semantic-correctness rule).
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.lib.common import (
    augment_iv_dosage_with_rate,
    build_dosage_instruction,
    resolve_iv_infusion_default,
)

# ── catalog resolver ──────────────────────────────────────────────────


def test_resolver_direct_key_hit():
    entry = resolve_iv_infusion_default("Ceftriaxone")
    assert entry["mode"] == "bolus"
    assert entry["duration_min"] == 30


def test_resolver_longest_prefix_wins():
    """The full authored dose string (`Ceftriaxone 1g IV q8h`) resolves to
    the drug entry, not to a shorter accidental prefix."""
    entry = resolve_iv_infusion_default("Ceftriaxone 1g IV q8h")
    assert entry["mode"] == "bolus"
    assert entry["duration_min"] == 30


def test_resolver_strips_protocol_prefix():
    """`IV_fluid: Normal saline` → `normal saline`."""
    entry = resolve_iv_infusion_default("IV_fluid: Normal saline")
    assert entry["mode"] == "continuous"
    assert entry["rate_value"] == 80
    assert entry["rate_unit"] == "mL/h"


def test_resolver_push_mode_returned():
    """Fentanyl is `push` — the resolver returns the entry so the caller
    can distinguish "known push" from "unknown drug"."""
    entry = resolve_iv_infusion_default("Fentanyl")
    assert entry["mode"] == "push"


def test_resolver_falls_back_to_default_for_unknown():
    entry = resolve_iv_infusion_default("Totally unknown drug xyz")
    assert entry["mode"] == "bolus"
    assert entry["duration_min"] == 30


def test_resolver_strips_leading_iv_qualifier():
    """Supportive order display_names sometimes carry the route as a
    prefix (``"IV normal saline 1000mL"``). Strip that leading token so
    the catalog lookup still resolves to the drug entry."""
    entry = resolve_iv_infusion_default("IV normal saline 1000mL")
    assert entry["mode"] == "continuous"
    assert entry["rate_value"] == 80


def test_resolver_alias_ns_to_normal_saline():
    """``"NS 80 mL/h"`` — the ``NS`` alias resolves via the aliases block."""
    entry = resolve_iv_infusion_default("NS 80 mL/h")
    assert entry["mode"] == "continuous"


def test_resolver_alias_after_protocol_strip():
    """``"IV_fluid: NS 80-125 mL/h"`` — strip prefix → ``"ns 80-125 ml/h"``
    → longest-prefix hit against aliases[``"ns"``] → normal saline."""
    entry = resolve_iv_infusion_default("IV_fluid: NS 80-125 mL/h")
    assert entry["mode"] == "continuous"
    assert entry["rate_value"] == 80


# ── augment_iv_dosage_with_rate — mode dispatch ────────────────────────


def _base_dosage() -> dict:
    return {"doseAndRate": [{"doseQuantity": {"value": 1, "unit": "g"}}]}


def test_continuous_emits_rate_quantity():
    d = _base_dosage()
    augment_iv_dosage_with_rate(d, dose_text="", route="IV", display_name="Normal saline")
    rq = d["doseAndRate"][0]["rateQuantity"]
    assert rq["value"] == 80
    assert rq["unit"] == "mL/h"


def test_bolus_emits_timing_duration():
    d = _base_dosage()
    augment_iv_dosage_with_rate(d, dose_text="", route="IV", display_name="Ceftriaxone")
    repeat = d["timing"]["repeat"]
    assert repeat["duration"] == 30
    assert repeat["durationUnit"] == "min"
    # rateQuantity is NOT populated for bolus (bolus rate is per-hospital-
    # pump policy; timing.duration is the canonical FHIR shape).
    assert "rateQuantity" not in d["doseAndRate"][0]


def test_bolus_preserves_existing_frequency():
    """Caller's frequency-derived timing block must not be clobbered."""
    d = {
        "doseAndRate": [{"doseQuantity": {"value": 1, "unit": "g"}}],
        "timing": {"repeat": {"frequency": 3, "period": 1, "periodUnit": "d"}},
    }
    augment_iv_dosage_with_rate(d, dose_text="", route="IV", display_name="Ceftriaxone")
    repeat = d["timing"]["repeat"]
    assert repeat["frequency"] == 3
    assert repeat["period"] == 1
    assert repeat["periodUnit"] == "d"
    assert repeat["duration"] == 30
    assert repeat["durationUnit"] == "min"


def test_push_is_no_op():
    """Fentanyl push MUST NOT get a fabricated rate."""
    d = _base_dosage()
    augment_iv_dosage_with_rate(d, dose_text="", route="IV", display_name="Fentanyl")
    assert "rateQuantity" not in d["doseAndRate"][0]
    assert "timing" not in d


def test_non_iv_route_is_no_op():
    d = _base_dosage()
    augment_iv_dosage_with_rate(d, dose_text="", route="PO", display_name="Ceftriaxone")
    assert "rateQuantity" not in d["doseAndRate"][0]
    assert "timing" not in d


def test_iv_route_case_insensitive():
    """Lowercase `iv` still resolves via canonicalize_route uppercasing."""
    d = _base_dosage()
    augment_iv_dosage_with_rate(d, dose_text="", route="iv", display_name="Ceftriaxone")
    assert d["timing"]["repeat"]["duration"] == 30


# ── priority 1: dose-text rate overrides catalog ──────────────────────


def test_dose_text_rate_wins_over_catalog():
    """Heparin catalog says 18 U/kg/h, but the authored dose string
    specifies 12 U/kg/h — honor the authored value."""
    d = _base_dosage()
    augment_iv_dosage_with_rate(
        d,
        dose_text="60U/kg bolus, then 12U/kg/h IV drip (target APTT 1.5-2.5x)",
        route="IV",
        display_name="Heparin",
    )
    rq = d["doseAndRate"][0]["rateQuantity"]
    assert rq["value"] == 12.0
    assert rq["unit"] == "U/kg/h"


def test_dose_text_ml_per_h():
    d = _base_dosage()
    augment_iv_dosage_with_rate(d, dose_text="100 mL/h IV", route="IV", display_name="Some maintenance fluid")
    rq = d["doseAndRate"][0]["rateQuantity"]
    assert rq["value"] == 100.0
    assert rq["unit"] == "mL/h"


def test_dose_text_hr_normalized_to_h():
    d = _base_dosage()
    augment_iv_dosage_with_rate(d, dose_text="50 mL/hr", route="IV", display_name="Something")
    rq = d["doseAndRate"][0]["rateQuantity"]
    assert rq["unit"] == "mL/h"


# ── integration with build_dosage_instruction ─────────────────────────


def test_build_dosage_instruction_iv_ceftriaxone_has_duration():
    order = {
        "display_name": "Ceftriaxone",
        "dose_quantity": 1.0,
        "dose_unit": "g",
        "frequency": "q8h",
        "frequency_per_day": 3,
        "route": "IV",
    }
    dosage = build_dosage_instruction(order, country="JP")
    assert dosage is not None
    assert dosage["timing"]["repeat"]["duration"] == 30
    assert dosage["timing"]["repeat"]["durationUnit"] == "min"


def test_build_dosage_instruction_iv_saline_has_rate():
    order = {
        "display_name": "Normal saline",
        "dose_quantity": 500,
        "dose_unit": "mL",
        "route": "IV",
    }
    dosage = build_dosage_instruction(order, country="JP")
    assert dosage is not None
    assert dosage["doseAndRate"][0]["rateQuantity"]["value"] == 80
    assert dosage["doseAndRate"][0]["rateQuantity"]["unit"] == "mL/h"


def test_build_dosage_instruction_po_gets_no_rate():
    order = {
        "display_name": "Amoxicillin",
        "dose_quantity": 500,
        "dose_unit": "mg",
        "route": "PO",
    }
    dosage = build_dosage_instruction(order, country="JP")
    assert dosage is not None
    dar = dosage.get("doseAndRate") or [{}]
    assert "rateQuantity" not in dar[0]


def test_build_dosage_instruction_iv_fentanyl_push_no_rate():
    order = {
        "display_name": "Fentanyl",
        "dose_quantity": 50,
        "dose_unit": "mcg",
        "route": "IV",
    }
    dosage = build_dosage_instruction(order, country="JP")
    assert dosage is not None
    dar = dosage.get("doseAndRate") or [{}]
    assert "rateQuantity" not in dar[0]
    # timing may or may not exist depending on frequency; but no duration.
    if "timing" in dosage:
        assert "duration" not in (dosage["timing"].get("repeat") or {})
