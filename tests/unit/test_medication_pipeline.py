"""Phase 1c-3 unit tests — hold_reason JA/EN localization coverage."""

from __future__ import annotations

from clinosim.simulator.medication_pipeline import (
    _HOLD_REASON_JA,
    _hold_reason_japanese,
)


class TestHoldReasonLocalization:
    def test_covers_every_disease_yaml_reason(self):
        """Phase 1c-3 (2026-09-22): the JP p=500 H100 audit surfaced 112
        raw-English leaks in the JA plan section because these disease-
        YAML ``reason`` strings had no JA lookup entry. The keys must
        match the YAML text VERBATIM."""
        expected_keys = {
            "AKI — lactic acidosis risk, renal clearance impaired",
            "AKI — NSAIDs contraindicated in renal impairment (afferent arteriolar vasoconstriction)",
            "AKI — ACE-I blocks efferent arteriolar tone, worsens renal hemodynamics (KDIGO 2012 § 3.5.2)",
            "AKI — ARB same efferent-arteriole mechanism as ACE-I (KDIGO 2012 § 3.5.2)",
            "Acute illness with lactic acidosis risk + NPO status",
            "Acute stroke — dysphagia / NG-tube risk contraindicates PO bisphosphonates (aspiration esophagitis)",
            "Active intracranial hemorrhage — anticoagulation contraindicated",
            "Active intracranial hemorrhage — antiplatelet contraindicated",
            "Sepsis — lactic acidosis risk, potential renal impairment",
            "DKA — lactic acidosis risk; resume after metabolic stabilization",
            "Acute HF exacerbation — oral diuretic replaced by IV furosemide",
        }
        for k in expected_keys:
            assert k in _HOLD_REASON_JA, f"missing JA translation for {k!r}"
            # Result must contain JA characters (not fall through to raw English).
            ja = _hold_reason_japanese(k)
            assert any("぀" <= ch <= "鿿" for ch in ja), f"JA translation for {k!r} looks non-JA: {ja!r}"

    def test_unknown_reason_falls_back_to_input(self):
        """Defensive default: unmapped reasons return the raw string so
        a novel disease YAML addition renders SOMETHING (English fallback)
        rather than an empty clause."""
        assert _hold_reason_japanese("never seen before") == "never seen before"
