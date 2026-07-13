"""session 48 cycle 8 拡張(案 D)imaging inference + stub emit テスト.

CIF-VS-FHIR-01 の silent-drop 修正:非-canonical path が生成する metadata なし
imaging Order も ImagingStudy として emit されることを確認。
"""
from __future__ import annotations

import pytest


@pytest.mark.unit
class TestInferImagingMetadata:
    def test_chest_xray_en(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        r = infer_imaging_metadata("Chest X-ray")
        assert r is not None
        assert r["modality"] == "CR"
        assert r["body_site_key"] == "chest"

    def test_chest_xray_jp(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        r = infer_imaging_metadata("胸部X線")
        assert r is not None and r["modality"] == "CR" and r["body_site_key"] == "chest"

    def test_head_ct_en(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        r = infer_imaging_metadata("Head CT")
        assert r is not None and r["modality"] == "CT" and r["body_site_key"] == "head"

    def test_head_ct_jp(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        r = infer_imaging_metadata("頭部CT")
        assert r is not None and r["modality"] == "CT" and r["body_site_key"] == "head"

    def test_abdominal_us_jp(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        r = infer_imaging_metadata("腹部エコー")
        assert r is not None and r["modality"] == "US" and r["body_site_key"] == "abdomen"

    def test_brain_mri_en(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        r = infer_imaging_metadata("Brain MRI")
        assert r is not None and r["modality"] == "MR" and r["body_site_key"] == "head"

    def test_kub_shorthand(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        r = infer_imaging_metadata("KUB")
        assert r is not None and r["modality"] == "CR" and r["body_site_key"] == "abdomen"

    def test_cxr_shorthand(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        r = infer_imaging_metadata("CXR")
        assert r is not None and r["modality"] == "CR"

    def test_body_site_snomed_populated(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        r = infer_imaging_metadata("Chest X-ray")
        # body_sites.yaml chest → 51185008
        assert r["body_site_snomed"] == "51185008"

    def test_unknown_returns_none(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        assert infer_imaging_metadata("Freetext imaging study") is None
        assert infer_imaging_metadata("") is None
        assert infer_imaging_metadata("random abbreviation ZZZ") is None

    def test_case_insensitive(self):
        from clinosim.modules.imaging.inference import infer_imaging_metadata
        assert infer_imaging_metadata("CHEST X-RAY") is not None
        assert infer_imaging_metadata("head ct") is not None
        assert infer_imaging_metadata("HEAD CT") is not None


@pytest.mark.unit
class TestEnricherInferencePath:
    def _make_ctx_and_run(self, orders):
        """metadata なし Order を含む minimum ctx で enricher を走らせる。"""
        from types import SimpleNamespace
        from clinosim.modules.imaging.engine import imaging_enricher as enrich_imaging
        record = SimpleNamespace(
            orders=orders,
            encounters=[],
            extensions={},
            disease_id="bacterial_pneumonia",
            severity="moderate",
        )
        ctx = SimpleNamespace(records=[record], master_seed=42)
        enrich_imaging(ctx)
        return record

    def test_enricher_inference_populates_metadata(self):
        from clinosim.types.encounter import Order, OrderStatus, OrderType
        # metadata 空、display_name="Chest X-ray" → inference で CR/chest populate
        o = Order(
            order_id="ORD-1", encounter_id="ENC-1", patient_id="POP-1",
            order_type=OrderType.IMAGING, display_name="Chest X-ray",
            status=OrderStatus.PLACED,
        )
        rec = self._make_ctx_and_run([o])
        studies = rec.extensions.get("imaging", [])
        assert len(studies) == 1
        s = studies[0]
        assert s.modality_code == "CR"
        assert s.body_site_snomed == "51185008"  # chest
        assert len(s.series) >= 1

    def test_enricher_stub_when_inference_fails(self):
        from clinosim.types.encounter import Order, OrderStatus, OrderType
        # inference 失敗 display_name → stub emit(series=[], modality="")
        o = Order(
            order_id="ORD-2", encounter_id="ENC-1", patient_id="POP-1",
            order_type=OrderType.IMAGING, display_name="ZZZ unknown study",
            status=OrderStatus.PLACED,
        )
        rec = self._make_ctx_and_run([o])
        studies = rec.extensions.get("imaging", [])
        assert len(studies) == 1
        s = studies[0]
        assert s.modality_code == ""
        assert s.body_site_snomed == ""
        assert s.series == []
        assert s.report is None
        # 空でもいい:study_id, encounter_id, patient_id, order_id は populated
        assert s.encounter_id == "ENC-1"
        assert s.order_id == "ORD-2"

    def test_enricher_still_handles_canonical_metadata_path(self):
        """既存 canonical path(metadata 完備)の regression がないこと。"""
        from clinosim.types.encounter import Order, OrderStatus, OrderType
        o = Order(
            order_id="ORD-3", encounter_id="ENC-1", patient_id="POP-1",
            order_type=OrderType.IMAGING, display_name="cxr",
            status=OrderStatus.PLACED,
            imaging_modality="CR",
            imaging_body_site_code="51185008",  # chest
            imaging_views=["PA"],
        )
        rec = self._make_ctx_and_run([o])
        studies = rec.extensions.get("imaging", [])
        assert len(studies) == 1
        assert studies[0].modality_code == "CR"
        assert studies[0].body_site_snomed == "51185008"
        assert len(studies[0].series) == 1
        assert studies[0].report is not None


@pytest.mark.unit
class TestFhirStubImagingStudy:
    def _build_and_get(self, study_record):
        from clinosim.modules.output._fhir_imaging_study import _build_imaging_study
        return _build_imaging_study(study_record, "ja", enc_reason_by_id={})

    def test_stub_emits_empty_modality_array(self):
        from clinosim.types.imaging import ImagingStudyRecord
        stub = ImagingStudyRecord(
            study_id="ENC-1-1", study_instance_uid="1.2.3.999",
            encounter_id="ENC-1", patient_id="POP-1",
            order_id="ORD-2", status="available",
            started_datetime="2026-06-30T10:00:00",
            modality_code="", body_site_snomed="",
            series=[], endpoint_id="", contrast=False, report=None,
        )
        r = self._build_and_get(stub)
        assert r["resourceType"] == "ImagingStudy"
        assert r["modality"] == []
        assert r["series"] == []
        assert r["numberOfSeries"] == 0
        # endpoint field は stub では省略(FHIR R4 endpoint は 0..*)
        assert "endpoint" not in r
        # basedOn は SR 参照が必ず emit(consumer が「オーダーはあった」を追跡できる)
        assert r["basedOn"][0]["reference"] == "ServiceRequest/sr-ORD-2"

    def test_full_study_unchanged(self):
        from clinosim.types.imaging import ImagingStudyRecord, ImagingSeries
        full = ImagingStudyRecord(
            study_id="ENC-1-1", study_instance_uid="1.2.3.999",
            encounter_id="ENC-1", patient_id="POP-1",
            order_id="ORD-3", status="available",
            started_datetime="2026-06-30T10:00:00",
            modality_code="CR", body_site_snomed="51185008",
            series=[ImagingSeries(
                series_uid="1.2.3.999.1", series_number=1,
                modality_code="CR", body_site_snomed="51185008",
                description="PA view", instance_count=1,
            )],
            endpoint_id="ep-1.2.3.999", contrast=False, report=None,
        )
        r = self._build_and_get(full)
        assert r["modality"][0]["code"] == "CR"
        assert r["numberOfSeries"] == 1
        assert r["endpoint"][0]["reference"] == "Endpoint/ep-1.2.3.999"
