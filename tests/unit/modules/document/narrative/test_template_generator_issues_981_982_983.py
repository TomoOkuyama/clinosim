"""Regression tests for Issues #981 / #982 / #983 narrative enrichment.

#981 — ED workup + disposition builders lift ctx.orders and encounter
       disposition into real narrative sentences instead of the 71%/68%
       boilerplate rate seen at v0.5.0 p=2000.
#982 — family_history builder walks ctx.family_history rather than
       always returning "特記家族歴なし" (was 100% placeholder rate).
#983 — chief_complaint builder rotates through per-disease variants
       via a deterministic SHA256 sub-seed on (patient_id, encounter_id),
       increasing distinct CC strings from 53 → >100 without RNG shift
       (variant selection is RNG-neutral per
       feedback_rng_neutral_additive_field).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import load_chief_complaint_variants
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile


def _make_ctx(
    *,
    document_type: DocumentType = DocumentType.ADMISSION_HP,
    target_lang: str = "ja",
    locale: str = "jp",
    disease_protocol: Any = None,
    encounter: Any = None,
    orders: list[Any] | None = None,
    family_history: list[Any] | None = None,
    lab_results: list[Any] | None = None,
    procedures: list[Any] | None = None,
    patient_id: str = "pt-test-981",
    encounter_id: str = "enc-test-981",
    severity: str = "moderate",
) -> NarrativeContext:
    patient = PatientProfile(patient_id=patient_id)
    if encounter is None:
        encounter = SimpleNamespace(
            encounter_id=encounter_id,
            encounter_type=SimpleNamespace(value="emergency"),
            admission_datetime=datetime(2026, 7, 1, 10, 0),
            chief_complaint="Cough and fever",
            chief_complaint_ja="",
            severity=severity,
            discharge_disposition="",
        )
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=getattr(encounter, "encounter_type", None),
        disease_protocol=disease_protocol,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity=severity,
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=lab_results or [],
        medications=[],
        diagnoses=[],
        procedures=procedures or [],
        allergies=[],
        document_type=document_type,
        target_lang=target_lang,
        locale=locale,
        orders=orders or [],
        family_history=family_history or [],
    )


# ─────────────────────────────────────────────────────────────────
# #982 — family_history builder
# ─────────────────────────────────────────────────────────────────


def test_family_history_empty_returns_fallback_ja() -> None:
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_family_history(ctx)
    assert text == "特記家族歴なし"
    assert facts == []


def test_family_history_walks_ctx_entries_ja() -> None:
    fams = [
        {"relationship": "MTH", "sex": "female", "deceased": True, "condition_codes": ["E11", "I63"]},
        {"relationship": "FTH", "sex": "male", "deceased": False, "condition_codes": ["I10"]},
        {"relationship": "NSIB", "sex": "female", "deceased": False, "condition_codes": ["C50"]},
    ]
    ctx = _make_ctx(family_history=fams)
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_family_history(ctx)
    assert text.startswith("家族歴: ")
    # Relationship labels present per relative.
    assert "母" in text
    assert "父" in text
    assert "兄弟姉妹" in text
    # Deceased marker on mother only.
    assert "母（故人）" in text
    assert "父（故人）" not in text
    # At least one disease display made it in (ICD-10-MHLW resolves E11).
    assert "糖尿" in text or "E11" in text
    assert "ctx.family_history" in facts


def test_family_history_all_empty_conditions_falls_back() -> None:
    """A relative record with no condition_codes carries no clinical
    signal — must not render "母 – 。" empty entries; fall back."""
    fams = [
        {"relationship": "MTH", "sex": "female", "deceased": False, "condition_codes": []},
        {"relationship": "FTH", "sex": "male", "deceased": False, "condition_codes": []},
    ]
    ctx = _make_ctx(family_history=fams)
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_family_history(ctx)
    assert text == "特記家族歴なし"
    assert facts == []


def test_family_history_en_locale_renders_english() -> None:
    fams = [{"relationship": "MTH", "sex": "female", "deceased": True, "condition_codes": ["E11"]}]
    ctx = _make_ctx(family_history=fams, target_lang="en", locale="us")
    gen = TemplateNarrativeGenerator()
    text, _ = gen._build_family_history(ctx)
    assert text.startswith("Family history:")
    assert "mother" in text.lower()
    assert "(deceased)" in text


# ─────────────────────────────────────────────────────────────────
# #981 — ED workup + disposition
# ─────────────────────────────────────────────────────────────────


def _order(**kwargs: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "order_id": "ORD-1",
        "encounter_id": "enc-test-981",
        "order_type": "lab",
        "display_name": "CBC",
        "panel_key": "",
        "imaging_modality": "",
        "order_code": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_ed_workup_lifts_orders_labs_and_imaging_ja() -> None:
    orders = [
        _order(order_type="lab", panel_key="CBC", display_name="CBC"),
        _order(order_id="ORD-2", order_type="lab", panel_key="BMP", display_name="BMP"),
        _order(order_id="ORD-3", order_type="imaging", imaging_modality="CR", display_name="Chest XR"),
        _order(order_id="ORD-4", order_type="imaging", imaging_modality="CT", display_name="Head CT"),
    ]
    ctx = _make_ctx(document_type=DocumentType.ED_NOTE, orders=orders)
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_ed_workup(ctx)
    assert "検査: " in text
    assert "CBC" in text and "BMP" in text
    assert "画像: " in text
    assert "Chest XR" in text and "Head CT" in text
    assert "ctx.orders.ed" in facts


def test_ed_workup_falls_back_when_no_orders() -> None:
    ctx = _make_ctx(document_type=DocumentType.ED_NOTE)
    gen = TemplateNarrativeGenerator()
    text, _ = gen._build_ed_workup(ctx)
    assert text == "検査・処置：特記事項なし"


def test_ed_workup_filters_orders_by_encounter_id() -> None:
    orders = [
        _order(order_type="lab", display_name="Foreign lab", encounter_id="enc-OTHER"),
        _order(order_id="ORD-2", order_type="lab", display_name="Local CBC", encounter_id="enc-test-981"),
    ]
    ctx = _make_ctx(document_type=DocumentType.ED_NOTE, orders=orders)
    gen = TemplateNarrativeGenerator()
    text, _ = gen._build_ed_workup(ctx)
    assert "Local CBC" in text
    assert "Foreign lab" not in text


def test_ed_disposition_home_includes_jtas_and_reason_ja() -> None:
    enc = SimpleNamespace(
        encounter_id="enc-test-981",
        encounter_type=SimpleNamespace(value="emergency"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        chief_complaint="Fever",
        chief_complaint_ja="発熱",
        severity="mild",
        discharge_disposition="home",
        triage_data=SimpleNamespace(level="4", level_system="JTAS", arrival_mode=""),
    )
    ctx = _make_ctx(document_type=DocumentType.ED_NOTE, encounter=enc)
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_ed_disposition(ctx)
    assert "自宅退院" in text
    assert "JTAS レベル 4" in text
    # Reason phrase comes from encounter.chief_complaint_ja.
    assert "発熱" in text
    assert "ctx.encounter.disposition" in facts


def test_ed_disposition_expired_matches_exp_disposition() -> None:
    enc = SimpleNamespace(
        encounter_id="enc-test-981",
        encounter_type=SimpleNamespace(value="emergency"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        chief_complaint="Cardiac arrest",
        chief_complaint_ja="心肺停止",
        severity="severe",
        discharge_disposition="exp",
    )
    ctx = _make_ctx(document_type=DocumentType.ED_NOTE, encounter=enc)
    gen = TemplateNarrativeGenerator()
    text, _ = gen._build_ed_disposition(ctx)
    assert "救急室内死亡" in text
    assert "家族" in text


def test_ed_disposition_admitted_uses_reason() -> None:
    proto = load_disease_protocol("acute_mi")
    enc = SimpleNamespace(
        encounter_id="enc-test-981",
        encounter_type=SimpleNamespace(value="emergency"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        chief_complaint="Chest pain",
        chief_complaint_ja="胸痛・冷汗・呼吸困難",
        severity="severe",
        discharge_disposition="hosp",
    )
    ctx = _make_ctx(document_type=DocumentType.ED_NOTE, encounter=enc, disease_protocol=proto)
    gen = TemplateNarrativeGenerator()
    text, _ = gen._build_ed_disposition(ctx)
    assert "入院適応" in text
    assert "胸痛" in text or "呼吸困難" in text


# ─────────────────────────────────────────────────────────────────
# #983 — chief_complaint variants
# ─────────────────────────────────────────────────────────────────


def test_chief_complaint_variant_pool_covers_every_disease() -> None:
    """Guard: every disease_id in modules/disease/reference_data has a
    variant pool entry. Regression test for the acceptance criterion in
    Issue #983 that no disease loses variant coverage on a future add.
    """
    import os

    disease_dir = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "..",
        "..",
        "clinosim",
        "modules",
        "disease",
        "reference_data",
    )
    disease_ids = {os.path.splitext(f)[0] for f in os.listdir(disease_dir) if f.endswith(".yaml")}
    variant_ids = set(load_chief_complaint_variants().keys())
    missing = disease_ids - variant_ids
    assert not missing, f"disease ids missing chief_complaint variants: {missing}"


def test_chief_complaint_variant_swap_is_deterministic() -> None:
    """Same (patient_id, encounter_id) → same variant. Determinism is the
    determinism-audit contract — variants use SHA256 sub-seed, so this
    holds even under a different RNG seed."""
    proto = load_disease_protocol("heart_failure_exacerbation")
    enc_kwargs = {
        "encounter_id": "enc-hf-1",
        "encounter_type": SimpleNamespace(value="inpatient"),
        "admission_datetime": datetime(2026, 7, 1, 10, 0),
        "chief_complaint": "Dyspnea on exertion, orthopnea, lower extremity edema",
        "chief_complaint_ja": "労作時呼吸困難・起座呼吸・下肢浮腫",
        "severity": "moderate",
        "discharge_disposition": "",
    }
    enc = SimpleNamespace(**enc_kwargs)
    ctx1 = _make_ctx(disease_protocol=proto, encounter=enc, patient_id="POP-HF-001", encounter_id="enc-hf-1")
    ctx2 = _make_ctx(disease_protocol=proto, encounter=enc, patient_id="POP-HF-001", encounter_id="enc-hf-1")
    gen = TemplateNarrativeGenerator()
    t1, _ = gen._build_chief_complaint(ctx1)
    t2, _ = gen._build_chief_complaint(ctx2)
    assert t1 == t2


def test_chief_complaint_variant_distribution_across_patients() -> None:
    """Iterating patient_ids for the same disease MUST produce >1 distinct
    CC string (variant swap actually kicks in). Regression guard for the
    pre-#983 100% same-string outcome per disease."""
    proto = load_disease_protocol("heart_failure_exacerbation")
    gen = TemplateNarrativeGenerator()
    seen: set[str] = set()
    for i in range(50):
        enc = SimpleNamespace(
            encounter_id=f"enc-hf-{i}",
            encounter_type=SimpleNamespace(value="inpatient"),
            admission_datetime=datetime(2026, 7, 1, 10, 0),
            chief_complaint="Dyspnea on exertion, orthopnea, lower extremity edema",
            chief_complaint_ja="労作時呼吸困難・起座呼吸・下肢浮腫",
            severity="moderate",
            discharge_disposition="",
        )
        ctx = _make_ctx(
            disease_protocol=proto,
            encounter=enc,
            patient_id=f"POP-HF-{i:03d}",
            encounter_id=f"enc-hf-{i}",
        )
        text, _ = gen._build_chief_complaint(ctx)
        seen.add(text)
    pool = load_chief_complaint_variants()["heart_failure_exacerbation"]
    assert len(seen) >= min(3, len(pool)), f"expected variants to rotate — saw {len(seen)}: {seen}"


def test_chief_complaint_variant_preserves_real_encounter_override() -> None:
    """Real per-encounter CC overrides (burns "手/腕の熱傷（部分層）") must
    NOT be replaced by a variant — swap only fires when the encounter
    CC equals the disease canonical.
    """
    proto = load_disease_protocol("heart_failure_exacerbation")
    enc = SimpleNamespace(
        encounter_id="enc-hf-99",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        chief_complaint="Custom real-world CC",
        chief_complaint_ja="実 CIF 上書き文言",  # ≠ disease canonical
        severity="moderate",
        discharge_disposition="",
    )
    ctx = _make_ctx(disease_protocol=proto, encounter=enc, encounter_id="enc-hf-99")
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_chief_complaint(ctx)
    assert text == "実 CIF 上書き文言"
    # No variant fact was appended.
    assert not any(f.startswith("chief_complaint_variants") for f in facts)


def test_chief_complaint_variant_only_ja_locale() -> None:
    """EN locale never picks a variant (variants are JP-only)."""
    proto = load_disease_protocol("heart_failure_exacerbation")
    enc = SimpleNamespace(
        encounter_id="enc-hf-1",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        chief_complaint="Dyspnea on exertion, orthopnea, lower extremity edema",
        chief_complaint_ja="",
        severity="moderate",
        discharge_disposition="",
    )
    ctx = _make_ctx(
        disease_protocol=proto,
        encounter=enc,
        target_lang="en",
        locale="us",
    )
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_chief_complaint(ctx)
    assert text == "Dyspnea on exertion, orthopnea, lower extremity edema"
    assert not any(f.startswith("chief_complaint_variants") for f in facts)
