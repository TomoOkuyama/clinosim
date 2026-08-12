"""Unit tests for the chronic-medication monitoring enricher (Issue #757)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.modules.monitoring.enricher import enrich_medication_monitoring
from clinosim.modules.monitoring.mapping import load_medication_monitoring, match_drugs
from clinosim.types.encounter import EncounterType, Order, OrderResult, OrderStatus, OrderType
from clinosim.types.patient import HomeMedication

pytestmark = pytest.mark.unit


# ---------- YAML loader ----------


class TestMappingLoader:
    def test_ships_warfarin_pair(self):
        mapping = load_medication_monitoring()
        assert "Warfarin" in mapping
        warfarin = mapping["Warfarin"]
        assert "ワルファリン" in warfarin.get("aliases", [])
        monitoring = warfarin["monitoring"]
        assert len(monitoring) >= 1
        pt_inr = next(m for m in monitoring if m["lab"] == "PT_INR")
        assert pt_inr["loinc"] == "6301-6"
        assert pt_inr.get("rationale")

    def test_ships_levothyroxine_pair(self):
        # #757 pass 3a
        mapping = load_medication_monitoring()
        assert "Levothyroxine" in mapping
        levo = mapping["Levothyroxine"]
        assert "レボチロキシン" in levo.get("aliases", [])
        monitoring = levo["monitoring"]
        assert len(monitoring) >= 1
        tsh = next(m for m in monitoring if m["lab"] == "TSH")
        assert tsh["loinc"] == "3016-3"
        assert tsh.get("rationale")

    def test_ships_dm_meds_hba1c_pairs(self):
        # #757 pass 3b — both Metformin and Insulin trigger HbA1c monitoring.
        mapping = load_medication_monitoring()
        assert "Metformin" in mapping
        assert "Insulin" in mapping
        met_labs = [m["lab"] for m in mapping["Metformin"]["monitoring"]]
        ins_labs = [m["lab"] for m in mapping["Insulin"]["monitoring"]]
        assert "HbA1c" in met_labs
        assert "HbA1c" in ins_labs
        met_hba1c = next(m for m in mapping["Metformin"]["monitoring"] if m["lab"] == "HbA1c")
        assert met_hba1c["loinc"] == "4548-4"
        # Insulin aliases cover the SC sliding-scale variant used by chronic_medications.yaml.
        assert "sliding scale insulin" in [a.lower() for a in mapping["Insulin"]["aliases"]]


class TestMatchDrugs:
    def setup_method(self):
        self.mapping = load_medication_monitoring()

    def _hm(self, drug_name: str) -> HomeMedication:
        return HomeMedication(drug_name=drug_name, route="PO")

    def test_case_insensitive_substring_english(self):
        assert match_drugs([self._hm("Warfarin 3mg PO")], self.mapping) == ["Warfarin"]

    def test_matches_japanese_alias(self):
        assert match_drugs([self._hm("ワルファリン 3mg")], self.mapping) == ["Warfarin"]

    def test_matches_coumadin_alias(self):
        assert match_drugs([self._hm("Coumadin 5mg PO daily")], self.mapping) == ["Warfarin"]

    def test_matches_levothyroxine_english(self):
        assert match_drugs([self._hm("Levothyroxine 50mcg PO daily")], self.mapping) == ["Levothyroxine"]

    def test_matches_levothyroxine_japanese_alias(self):
        assert match_drugs([self._hm("レボチロキシン 50mcg")], self.mapping) == ["Levothyroxine"]

    def test_matches_multiple_drugs_when_patient_on_both(self):
        meds = [self._hm("Warfarin 3mg"), self._hm("Levothyroxine 50mcg")]
        assert set(match_drugs(meds, self.mapping)) == {"Warfarin", "Levothyroxine"}

    def test_matches_metformin(self):
        # #757 pass 3b — Metformin from chronic_medications.yaml E11.9 block.
        assert match_drugs([self._hm("Metformin 500mg PO bid")], self.mapping) == ["Metformin"]

    def test_matches_sliding_scale_insulin_via_insulin_alias(self):
        # #757 pass 3b — SC sliding-scale insulin is the E11.9 second-line drug.
        assert match_drugs([self._hm("Sliding scale insulin")], self.mapping) == ["Insulin"]

    def test_dm_patient_on_metformin_and_insulin_matches_both(self):
        # Patient on both DM drugs → both entries fire but the enricher
        # dedups on analyte name so only one HbA1c injection happens.
        meds = [self._hm("Metformin 500mg"), self._hm("Sliding scale insulin")]
        assert set(match_drugs(meds, self.mapping)) == {"Metformin", "Insulin"}

    def test_no_match_returns_empty(self):
        assert match_drugs([self._hm("Aspirin 81mg")], self.mapping) == []

    def test_plain_string_medications_supported(self):
        # Defensive: legacy call sites / tests may pass plain strings.
        assert match_drugs(["Warfarin 3mg"], self.mapping) == ["Warfarin"]

    def test_empty_list_returns_empty(self):
        assert match_drugs([], self.mapping) == []
        assert match_drugs(None, self.mapping) == []


# ---------- Enricher ----------


def _build_record(
    *,
    patient_id: str = "POP-000042",
    on_warfarin: bool = True,
    on_levothyroxine: bool = False,
    on_metformin: bool = False,
    on_insulin: bool = False,
    has_dm: bool = False,
    encounter_type: EncounterType = EncounterType.OUTPATIENT,
    existing_orders: list[Order] | None = None,
) -> Any:
    """Assemble a minimal record + patient + encounter shape the enricher can walk."""
    meds: list[HomeMedication] = []
    if on_warfarin:
        meds.append(HomeMedication(drug_name="Warfarin 3mg", route="PO"))
    if on_levothyroxine:
        meds.append(HomeMedication(drug_name="Levothyroxine 50mcg", route="PO"))
    if on_metformin:
        meds.append(HomeMedication(drug_name="Metformin 500mg", route="PO"))
    if on_insulin:
        meds.append(HomeMedication(drug_name="Sliding scale insulin", route="SC"))
    chronic: list[Any] = []
    if has_dm:
        chronic.append(SimpleNamespace(code="E11.9"))
    patient = SimpleNamespace(
        patient_id=patient_id,
        sex="M",
        age=72,
        current_medications=meds,
        chronic_conditions=chronic,
    )
    encounter = SimpleNamespace(
        encounter_id=f"ENC-{patient_id}-001",
        encounter_type=encounter_type,
        admission_datetime=datetime(2025, 3, 15, 10, 0),
        attending_physician_id="STAFF-DOC-001",
    )
    record = SimpleNamespace(
        patient=patient,
        encounters=[encounter],
        orders=list(existing_orders or []),
        lab_results=[],
    )
    return record


def _build_ctx(records: list[Any]) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(country="US"),
        master_seed=42,
        records=records,
    )


class TestEnricher:
    def test_no_op_when_patient_has_no_medications(self):
        rec = _build_record(on_warfarin=False)
        enrich_medication_monitoring(_build_ctx([rec]))
        assert rec.orders == []
        assert rec.lab_results == []

    def test_injects_pt_inr_for_warfarin_outpatient(self):
        rec = _build_record()
        enrich_medication_monitoring(_build_ctx([rec]))
        assert len(rec.orders) == 1
        order = rec.orders[0]
        assert order.order_type == OrderType.LAB
        assert order.display_name == "PT_INR"
        assert order.order_code == "6301-6"
        assert "Warfarin" in order.clinical_intent
        assert order.status == OrderStatus.RESULTED
        assert order.result is not None
        # Therapeutic range (2.0-3.0 target with modest noise); allow band 1.5-4.5.
        assert 1.5 <= float(order.result.value) <= 4.5
        assert order.result.lab_name == "PT_INR"
        assert order.result.unit == "{INR}"
        # Same result also appended to record.lab_results.
        assert len(rec.lab_results) == 1
        assert rec.lab_results[0] is order.result

    def test_dedup_when_existing_pt_inr_order(self):
        existing = Order(
            order_id="ORD-DIS-PTINR",
            display_name="PT_INR",
            order_type=OrderType.LAB,
            status=OrderStatus.RESULTED,
            result=OrderResult(lab_name="PT_INR", value=2.6, unit="{INR}"),
        )
        rec = _build_record(existing_orders=[existing])
        enrich_medication_monitoring(_build_ctx([rec]))
        # No new order added — existing PT-INR from disease YAML is respected.
        assert len(rec.orders) == 1
        assert rec.orders[0] is existing
        assert rec.lab_results == []

    def test_determinism_across_repeated_runs(self):
        rec_a = _build_record()
        rec_b = _build_record()
        enrich_medication_monitoring(_build_ctx([rec_a]))
        enrich_medication_monitoring(_build_ctx([rec_b]))
        assert rec_a.orders[0].result.value == rec_b.orders[0].result.value
        assert rec_a.orders[0].ordered_datetime == rec_b.orders[0].ordered_datetime

    def test_different_patient_ids_produce_different_values(self):
        rec_a = _build_record(patient_id="POP-000001")
        rec_b = _build_record(patient_id="POP-000999")
        enrich_medication_monitoring(_build_ctx([rec_a]))
        enrich_medication_monitoring(_build_ctx([rec_b]))
        # Values should differ (different sub-RNG stream per patient).
        # Statistically overwhelmingly likely; the sub-RNG derivation is
        # per-patient so byte-identical values would flag a seeding bug.
        assert rec_a.orders[0].result.value != rec_b.orders[0].result.value

    def test_prefers_outpatient_when_multiple_encounters(self):
        rec = _build_record()
        # Prepend an inpatient encounter; enricher must still choose the OUTPATIENT one.
        inpatient = SimpleNamespace(
            encounter_id="ENC-INP-999",
            encounter_type=EncounterType.INPATIENT,
            admission_datetime=datetime(2025, 2, 1, 12, 0),
            attending_physician_id="STAFF-DOC-999",
        )
        rec.encounters = [inpatient, rec.encounters[0]]
        enrich_medication_monitoring(_build_ctx([rec]))
        assert len(rec.orders) == 1
        # Encounter_id on the injected order points to the outpatient encounter.
        assert rec.orders[0].encounter_id == "ENC-POP-000042-001"

    def test_no_op_when_no_encounters(self):
        rec = _build_record()
        rec.encounters = []
        enrich_medication_monitoring(_build_ctx([rec]))
        assert rec.orders == []
        assert rec.lab_results == []

    def test_injects_tsh_for_levothyroxine_outpatient(self):
        # #757 pass 3a — TSH is not physiology-modeled; verifies BASELINE_LAB_NORMALS
        # fallback kicks in so we don't skip the injection on `true_value is None`.
        rec = _build_record(on_warfarin=False, on_levothyroxine=True)
        enrich_medication_monitoring(_build_ctx([rec]))
        assert len(rec.orders) == 1
        order = rec.orders[0]
        assert order.display_name == "TSH"
        assert order.order_code == "3016-3"
        assert "Levothyroxine" in order.clinical_intent
        assert order.status == OrderStatus.RESULTED
        assert order.result is not None
        # Normal reference-range emit with light noise; allow 0.5-5.5 (well within
        # the physiologic 3.0-18.0 limits but around the 2.5 mIU/L baseline center).
        assert 0.5 <= float(order.result.value) <= 5.5
        assert order.result.lab_name == "TSH"
        assert order.result.unit == "m[IU]/L"

    def test_injects_both_labs_when_patient_on_warfarin_and_levothyroxine(self):
        rec = _build_record(on_warfarin=True, on_levothyroxine=True)
        enrich_medication_monitoring(_build_ctx([rec]))
        analytes = {o.display_name for o in rec.orders}
        assert analytes == {"PT_INR", "TSH"}
        assert len(rec.lab_results) == 2

    def test_injects_hba1c_for_dm_patient_on_metformin(self):
        # #757 pass 3b — DM patient on Metformin gets HbA1c.
        rec = _build_record(on_warfarin=False, on_metformin=True, has_dm=True)
        enrich_medication_monitoring(_build_ctx([rec]))
        assert len(rec.orders) == 1
        order = rec.orders[0]
        assert order.display_name == "HbA1c"
        assert order.order_code == "4548-4"
        assert "Metformin" in order.clinical_intent
        assert order.result is not None
        # DM patients emit physiology-modeled HbA1c 5-14% range depending on glycemic control.
        assert 4.0 <= float(order.result.value) <= 15.0
        assert order.result.unit == "%"

    def test_dedup_hba1c_when_patient_on_both_metformin_and_insulin(self):
        # #757 pass 3b — Metformin + Insulin both map to HbA1c; dedup ensures
        # only ONE HbA1c injection, not two.
        rec = _build_record(on_warfarin=False, on_metformin=True, on_insulin=True, has_dm=True)
        enrich_medication_monitoring(_build_ctx([rec]))
        analytes = [o.display_name for o in rec.orders]
        assert analytes.count("HbA1c") == 1, f"expected 1 HbA1c injection, got {analytes}"

    def test_no_op_when_master_rng_untouched(self):
        # RNG-preservation invariant: an enricher run must never advance the
        # `master rng` (approximated here by "we take master_seed as a value,
        # not from an rng.consume()"). Sanity check via signature — nothing
        # in the enricher accepts an rng parameter, so this is a doc-shape test.
        import inspect

        sig = inspect.signature(enrich_medication_monitoring)
        params = list(sig.parameters)
        assert params == ["ctx"], (
            "enricher must take only (ctx: EnricherContext); if this grows, "
            "audit for master-rng consumption per RNG-preservation policy."
        )
