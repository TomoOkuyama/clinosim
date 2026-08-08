"""End-to-end firing proof for `dose_ja` / `dose_en` disease-YAML fields (Issue #476).

Silent-drop concern noted in the Issue body: `DiseaseProtocol.drugs` is
`dict[str, Any]`, so `extra="forbid"` does not guard drug-entry keys.
An `dose_ja` field added to the YAML without a consumer wire-up would be
silently swallowed — the failure mode is invisible in FHIR output.

This test exercises the two consumer paths that #476 wires:
* `_build_dosage_instruction` — used by inpatient MedicationRequest / MAR
  and by the escalation-Order path (`_place_escalation_orders` at
  `inpatient.py:1216`).
* `_build_discharge_medication_request` — used by the discharge-Rx builder
  (`_bb_discharge_medication_requests` at `fhir_r4_adapter.py:682`) reading
  `discharge_prescription.items[]` dicts populated by
  `_build_discharge_rx._append_item`.

Both country slots are exercised (JP → `dose_ja`, US → `dose_en`).
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestBuildDosageInstruction:
    """Order-side path (`_build_dosage_instruction` in `_fhir_common`)."""

    def test_jp_uses_dose_text_ja_when_structured_empty(self):
        from clinosim.modules.output.fhir_r4.common import _build_dosage_instruction

        order = {
            "dose_quantity": None,
            "dose_unit": "",
            "frequency": "",
            "route": None,
            "dose_text_ja": "以前の吸入薬を再開または新規開始",
            "dose_text_en": "Resume or initiate controller therapy",
        }
        result = _build_dosage_instruction(order, country="JP")
        assert result == {"text": "以前の吸入薬を再開または新規開始"}

    def test_us_uses_dose_text_en_when_structured_empty(self):
        from clinosim.modules.output.fhir_r4.common import _build_dosage_instruction

        order = {
            "dose_quantity": None,
            "dose_unit": "",
            "frequency": "",
            "route": None,
            "dose_text_ja": "以前の吸入薬を再開または新規開始",
            "dose_text_en": "Resume or initiate controller therapy",
        }
        result = _build_dosage_instruction(order, country="US")
        assert result == {"text": "Resume or initiate controller therapy"}

    def test_authored_text_wins_over_structured_summary(self):
        """Even when structured route is present, the author's instruction
        takes precedence for the text summary — the auto-derived summary
        can't reconstruct instruction-only doses."""
        from clinosim.modules.output.fhir_r4.common import _build_dosage_instruction

        order = {
            "dose_quantity": None,
            "dose_unit": "",
            "frequency": "",
            "route": "INH",
            "dose_text_ja": "以前の吸入薬を再開または新規開始",
        }
        result = _build_dosage_instruction(order, country="JP")
        # Route is still emitted as a coded field
        assert result is not None
        assert "route" in result
        # But text is the authored instruction, not the auto-derived summary
        assert result["text"] == "以前の吸入薬を再開または新規開始"

    def test_none_when_empty_and_no_authored_text(self):
        """Issue #467 invariant preserved: no text, no dose → return None."""
        from clinosim.modules.output.fhir_r4.common import _build_dosage_instruction

        order = {
            "dose_quantity": None,
            "dose_unit": "",
            "frequency": "",
            "route": None,
            "dose_text_ja": "",
            "dose_text_en": "",
        }
        assert _build_dosage_instruction(order, country="JP") is None

    def test_us_falls_through_when_only_ja_authored(self):
        """A JP-only authored instruction should NOT leak into US output."""
        from clinosim.modules.output.fhir_r4.common import _build_dosage_instruction

        order = {
            "dose_quantity": None,
            "dose_unit": "",
            "frequency": "",
            "route": None,
            "dose_text_ja": "INR 2.0-3.0 に調整 (70 歳以上は 1.5-2.5)",
            "dose_text_en": "",
        }
        # US path: no dose_en, no structured → None
        assert _build_dosage_instruction(order, country="US") is None


@pytest.mark.unit
class TestBuildDischargeMedicationRequest:
    """Discharge-Rx path (`_build_discharge_medication_request` in `_fhir_medications`)."""

    def _item(self, **overrides):
        base = {
            "drug_name": "ICS/LABA inhaler",
            "dose": "",
            "route": "INH",
            "duration_days": 7,
            "dose_ja": "以前の吸入薬を再開または新規開始",
            "dose_en": "Resume or initiate controller therapy",
        }
        base.update(overrides)
        return base

    def test_jp_discharge_uses_dose_ja(self):
        from clinosim.modules.output.fhir_r4.builders.medications import _build_discharge_medication_request

        r = _build_discharge_medication_request(
            self._item(),
            patient_id="P1",
            encounter_id="ENC1",
            encounter_type="inpatient",
            country="JP",
            seq=1,
            authored_on="2026-08-01T09:00:00+09:00",
        )
        di = r.get("dosageInstruction", [])
        assert len(di) == 1
        assert di[0].get("text") == "以前の吸入薬を再開または新規開始"

    def test_us_discharge_uses_dose_en(self):
        from clinosim.modules.output.fhir_r4.builders.medications import _build_discharge_medication_request

        r = _build_discharge_medication_request(
            self._item(),
            patient_id="P1",
            encounter_id="ENC1",
            encounter_type="inpatient",
            country="US",
            seq=1,
            authored_on="2026-08-01T09:00:00Z",
        )
        di = r.get("dosageInstruction", [])
        assert len(di) == 1
        assert di[0].get("text") == "Resume or initiate controller therapy"


@pytest.mark.unit
class TestKeyTypoValidator:
    """`dose_jp` / `dose_us` etc. must fail-loud at load time (Issue #476 silent-drop defense)."""

    def test_dose_jp_typo_rejected(self):
        from clinosim.modules.disease.protocol import _validate_drug_entry_localized_dose_keys

        drugs = {"discharge_oral": {"japan": [{"drug": "X", "dose_jp": "typo"}]}}
        with pytest.raises(ValueError, match="Issue #476"):
            _validate_drug_entry_localized_dose_keys("test_disease", drugs)

    def test_dose_us_typo_rejected(self):
        from clinosim.modules.disease.protocol import _validate_drug_entry_localized_dose_keys

        drugs = {"discharge_oral": {"us": [{"drug": "X", "dose_us": "typo"}]}}
        with pytest.raises(ValueError, match="Issue #476"):
            _validate_drug_entry_localized_dose_keys("test_disease", drugs)

    def test_canonical_keys_accepted(self):
        from clinosim.modules.disease.protocol import _validate_drug_entry_localized_dose_keys

        drugs = {
            "discharge_oral": {
                "japan": [{"drug": "X", "dose_ja": "OK", "dose_en": "OK"}],
                "us": [{"drug": "Y", "dose_en": "OK"}],
            }
        }
        _validate_drug_entry_localized_dose_keys("test_disease", drugs)  # must not raise
