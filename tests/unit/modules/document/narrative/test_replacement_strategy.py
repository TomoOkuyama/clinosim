"""Tests for apply_replacement_strategy (Task 7 α-min-1; migrated to N-chain IF).

The local LLMProvider Protocol is deleted — the strategy takes an LLMService
and calls complete_prompt (AD-11). Tests use MockProvider-backed LLMService.
"""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.document.narrative.replacement_strategy import (
    apply_replacement_strategy,
)
from clinosim.modules.llm_service.engine import LLMService, LLMTaskType
from clinosim.modules.llm_service.providers import MockProvider
from clinosim.types.document import (
    DocumentType,
    DocumentTypeSpec,
    FormatType,
    NarrativeContext,
    NarrativeOutput,
)

# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _make_spec(
    stage2_strategy: str = "template_only",
    llm_enabled_sections: tuple[str, ...] = (),
    format_type: FormatType = FormatType.COMPOSITION,
) -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="admission_hp",
        loinc_code="34117-2",
        format_type=format_type,
        countries_supported=("jp", "us"),
        generation_frequency="admission_once",
        composition_sections=("hpi", "assessment_and_plan"),
        stage2_strategy=stage2_strategy,
        llm_enabled_sections=llm_enabled_sections,
    )


def _make_template_output(sections: dict[str, str] | None = None) -> NarrativeOutput:
    return NarrativeOutput(
        sections=sections
        or {
            "hpi": "Template HPI text",
            "assessment_and_plan": "Template A&P text",
        },
        metadata={"generator": "template", "lang": "ja"},
        facts_used=["ctx.day_index"],
    )


def _make_ctx() -> NarrativeContext:
    patient = SimpleNamespace(age=55, sex="M", chronic_conditions=[])
    encounter = SimpleNamespace(encounter_id="enc-test")
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ADMISSION_HP,
        target_lang="ja",
        locale="jp",
    )


def _mock_llm(provider: MockProvider | None = None) -> LLMService:
    return LLMService(
        mode="llm",
        narrative_provider=provider if provider is not None else MockProvider(),
        narrative_model_map={"medium": "mock"},
        provider_name_narrative="mock",
        retry_attempts=1,
        retry_backoff_seconds=0.0,
    )


def _apply(template_output, ctx, spec, llm, **kwargs):
    return apply_replacement_strategy(
        template_output,
        ctx,
        spec,
        llm,
        task_type=LLMTaskType.ADMISSION_HP,
        language=ctx.target_lang,
        **kwargs,
    )


# ─────────────────────────────────────────────────────────────────
# template_only strategy
# ─────────────────────────────────────────────────────────────────


def test_template_only_strategy_returns_template_unchanged() -> None:
    """template_only: template output returned verbatim, LLM not called."""
    spec = _make_spec(stage2_strategy="template_only")
    template_output = _make_template_output()
    provider = MockProvider()
    ctx = _make_ctx()

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    assert result is template_output
    assert provider.call_count == 0


def test_template_only_strategy_preserves_all_fields() -> None:
    """template_only: all NarrativeOutput fields preserved exactly."""
    spec = _make_spec(stage2_strategy="template_only")
    template_output = _make_template_output({"hpi": "original hpi"})
    ctx = _make_ctx()

    result = _apply(template_output, ctx, spec, _mock_llm())

    assert result.sections["hpi"] == "original hpi"
    assert result.metadata["generator"] == "template"


# ─────────────────────────────────────────────────────────────────
# template_seed strategy
# ─────────────────────────────────────────────────────────────────


def test_template_seed_strategy_passes_template_as_seed_to_llm() -> None:
    """template_seed: the LLM receives a prompt containing the template text."""
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),
    )
    template_output = _make_template_output({"hpi": "Template HPI text", "assessment_and_plan": "A&P"})
    ctx = _make_ctx()
    provider = MockProvider()

    _apply(template_output, ctx, spec, _mock_llm(provider))

    assert provider.call_count == 1
    assert "Template HPI text" in provider.last_prompt  # template seed in prompt


def test_template_seed_strategy_only_replaces_llm_enabled_sections() -> None:
    """template_seed: only llm_enabled_sections are replaced; others pass through."""
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),
    )
    template_output = _make_template_output(
        {
            "hpi": "Template HPI text",
            "assessment_and_plan": "Template A&P text",
        }
    )
    ctx = _make_ctx()
    provider = MockProvider()

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    # LLM-enabled section replaced
    assert result.sections["hpi"].startswith("[Mock LLM response")
    # Non-LLM section unchanged
    assert result.sections["assessment_and_plan"] == "Template A&P text"
    # raw_text / facts_used preserved (unmodified template base)
    assert result.raw_text == template_output.raw_text
    assert result.facts_used == template_output.facts_used


def test_template_seed_strategy_calls_llm_per_enabled_section() -> None:
    """template_seed: one LLM call per enabled section."""
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi", "assessment_and_plan"),
    )
    template_output = _make_template_output()
    ctx = _make_ctx()
    provider = MockProvider()

    _apply(template_output, ctx, spec, _mock_llm(provider))

    assert provider.call_count == 2


# ─────────────────────────────────────────────────────────────────
# Unknown strategy — safe default
# ─────────────────────────────────────────────────────────────────


def test_unknown_strategy_falls_back_to_template() -> None:
    """Unknown stage2_strategy: template output returned (safe default)."""
    spec = _make_spec(stage2_strategy="future_unknown_strategy")
    template_output = _make_template_output()
    ctx = _make_ctx()
    provider = MockProvider()

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    assert result is template_output
    assert provider.call_count == 0


# ─────────────────────────────────────────────────────────────────
# Cache integration
# ─────────────────────────────────────────────────────────────────


def test_template_seed_with_empty_llm_enabled_sections_returns_template_unchanged() -> None:
    """If stage2_strategy is template_seed but llm_enabled_sections is empty,
    the strategy must safely return the template output unchanged (no
    LLM call, no section mutation).

    Verifies the invariant documented in _apply_template_seed_strategy:
    'When llm_enabled_sections is empty, no LLM call is made and the
    returned output is byte-identical to template_output (safe no-op).'
    """
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=(),  # ★ empty
        format_type=FormatType.COMPOSITION,
    )
    template_output = _make_template_output({"section_a": "template content"})
    ctx = _make_ctx()
    provider = MockProvider()  # should NOT be called

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    assert provider.call_count == 0
    assert result.sections["section_a"] == "template content"


def test_template_seed_strategy_uses_cache_on_hit() -> None:
    """NarrativeCache hit: LLM not called on second request with same key."""
    from clinosim.modules.document.narrative.cache import NarrativeCache

    cache = NarrativeCache()

    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),
    )
    template_output = _make_template_output({"hpi": "Template HPI text"})
    ctx = _make_ctx()
    provider = MockProvider()
    llm = _mock_llm(provider)

    # First call — cache miss → LLM invoked
    _apply(template_output, ctx, spec, llm, cache_get=cache.get, cache_put=cache.put)
    assert provider.call_count == 1

    # Second call — same context → cache hit → LLM NOT invoked again
    _apply(template_output, ctx, spec, llm, cache_get=cache.get, cache_put=cache.put)
    assert provider.call_count == 1  # still 1, not 2


def test_template_seed_different_patients_different_seeds_no_cache_collision() -> None:
    """C-1 pin (N-chain adv-1): distinct patients with distinct template seeds
    must produce distinct cache keys → one provider call EACH.

    Before the fix, dict patients all bucketed to "0s-U" and the key collapsed
    to (lang, section): the whole cohort shared one cache entry per section
    (2 patients → 1 provider call, identical hpi text = cross-patient
    narrative contamination).
    """
    from clinosim.modules.document.narrative.cache import NarrativeCache

    cache = NarrativeCache()

    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    provider = MockProvider()
    llm = _mock_llm(provider)

    # Production pass path shape: ctx.patient is a JSON-deserialized dict.
    ctx_a = _make_ctx()
    ctx_a.patient = {"age": 55, "sex": "M"}
    ctx_b = _make_ctx()
    ctx_b.patient = {"age": 82, "sex": "F"}

    out_a = _apply(
        _make_template_output({"hpi": "HPI for patient A, 55M, pneumonia"}),
        ctx_a,
        spec,
        llm,
        cache_get=cache.get,
        cache_put=cache.put,
    )
    out_b = _apply(
        _make_template_output({"hpi": "HPI for patient B, 82F, heart failure"}),
        ctx_b,
        spec,
        llm,
        cache_get=cache.get,
        cache_put=cache.put,
    )

    assert provider.call_count == 2, "second patient must NOT hit the first's cache entry"
    assert out_a.sections["hpi"] != out_b.sections["hpi"]
    assert len(cache) == 2  # two distinct cache keys stored


def test_template_seed_identical_seed_and_bucket_reuses_cache() -> None:
    """C-1: genuinely identical seeds in the same clinical bucket still share
    one cache entry (cross-patient reuse preserved) — 1 provider call total.
    """
    from clinosim.modules.document.narrative.cache import NarrativeCache

    cache = NarrativeCache()

    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    provider = MockProvider()
    llm = _mock_llm(provider)

    ctx_a = _make_ctx()
    ctx_a.patient = {"age": 55, "sex": "M"}
    ctx_b = _make_ctx()
    ctx_b.patient = {"age": 57, "sex": "M"}  # same 50s-M bucket

    shared = {"hpi": "Identical template seed text"}
    _apply(_make_template_output(dict(shared)), ctx_a, spec, llm, cache_get=cache.get, cache_put=cache.put)
    _apply(_make_template_output(dict(shared)), ctx_b, spec, llm, cache_get=cache.get, cache_put=cache.put)

    assert provider.call_count == 1  # cache hit: identical seed + bucket


def test_local_llm_provider_protocol_deleted() -> None:
    """N-2: the module-local LLMProvider Protocol is removed (AD-11 unification)."""
    import clinosim.modules.document.narrative.replacement_strategy as mod

    assert not hasattr(mod, "LLMProvider")


# ─────────────────────────────────────────────────────────────────
# Session-88j Tier 1: free_text raw_text rejoin after LLM replacement
# (progress_note pattern — DocumentReference emit reads raw_text)
# ─────────────────────────────────────────────────────────────────


def _free_text_spec() -> DocumentTypeSpec:
    """FREE_TEXT spec mirroring the progress_note post-88j shape."""
    return DocumentTypeSpec(
        type_key="progress_note",
        loinc_code="11506-3",
        format_type=FormatType.FREE_TEXT,
        countries_supported=("jp", "us"),
        generation_frequency="daily",
        composition_sections=("subjective", "objective", "assessment", "plan"),
        stage2_strategy="template_seed",
        llm_enabled_sections=("subjective", "assessment", "plan"),
    )


def _free_text_template_output() -> NarrativeOutput:
    """Template output shaped like `_render_progress_note_text`: sections +
    raw_text + `raw_text_rejoin` metadata."""
    sections = {
        "subjective": "患者は倦怠感の訴えあり",
        "objective": "T 37.2 / HR 78 / SpO2 96",
        "assessment": "感染性肺炎の増悪傾向なし",
        "plan": "同治療継続",
    }
    labels = [
        ("S（主観）", "subjective"),
        ("O（客観）", "objective"),
        ("A（評価）", "assessment"),
        ("P（計画）", "plan"),
    ]
    raw_text = "\n".join(f"{label} {sections[key]}" for label, key in labels)
    return NarrativeOutput(
        raw_text=raw_text,
        sections=sections,
        metadata={
            "generator": "template",
            "lang": "ja",
            "raw_text_rejoin": {"separator": "\n", "order": labels},
        },
        facts_used=["ctx.day_index"],
    )


def test_free_text_template_seed_rebuilds_raw_text_with_llm_sections() -> None:
    """FREE_TEXT + template_seed: `raw_text` is rebuilt from the possibly-
    replaced sections using the renderer-set label order. The LLM-eligible
    sections carry `[Mock LLM response ...]` while `objective` stays as
    the template original."""
    spec = _free_text_spec()
    template_output = _free_text_template_output()
    ctx = _make_ctx()
    provider = MockProvider()

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    # 3 LLM calls, one per llm_enabled_sections entry
    assert provider.call_count == 3
    # LLM-replaced sections reflected in raw_text
    assert result.sections["subjective"].startswith("[Mock LLM response")
    assert result.sections["assessment"].startswith("[Mock LLM response")
    assert result.sections["plan"].startswith("[Mock LLM response")
    # objective stays templated
    assert result.sections["objective"] == "T 37.2 / HR 78 / SpO2 96"
    # raw_text now reflects the LLM sections + template objective, preserving
    # the S / O / A / P label order
    assert result.raw_text.startswith("S（主観） [Mock LLM response")
    assert "O（客観） T 37.2" in result.raw_text  # unchanged objective
    assert "A（評価） [Mock LLM response" in result.raw_text
    assert "P（計画） [Mock LLM response" in result.raw_text
    # Section order preserved
    s_pos = result.raw_text.index("S（主観）")
    o_pos = result.raw_text.index("O（客観）")
    a_pos = result.raw_text.index("A（評価）")
    p_pos = result.raw_text.index("P（計画）")
    assert s_pos < o_pos < a_pos < p_pos


def test_free_text_template_seed_no_rebuild_when_no_llm_sections() -> None:
    """When `llm_enabled_sections` is empty the raw_text stays as the
    template original — no LLM call, no rejoin (safe no-op)."""
    spec = DocumentTypeSpec(
        type_key="progress_note",
        loinc_code="11506-3",
        format_type=FormatType.FREE_TEXT,
        countries_supported=("jp", "us"),
        generation_frequency="daily",
        composition_sections=("subjective", "objective", "assessment", "plan"),
        stage2_strategy="template_seed",
        llm_enabled_sections=(),  # dead wiring — nothing to replace
    )
    template_output = _free_text_template_output()
    ctx = _make_ctx()
    provider = MockProvider()

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    assert provider.call_count == 0
    assert result.raw_text == template_output.raw_text  # untouched


# ─────────────────────────────────────────────────────────────────
# Session-88j Tier 1: template_seed_bundle strategy (1 call per doc)
# ─────────────────────────────────────────────────────────────────


def _bundle_spec(
    llm_enabled_sections: tuple[str, ...] = ("subjective", "assessment", "plan"),
    format_type: FormatType = FormatType.COMPOSITION,
    type_key: str = "outpatient_soap",
    composition_sections: tuple[str, ...] = ("subjective", "objective", "assessment", "plan"),
) -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key=type_key,
        loinc_code="34131-3",
        format_type=format_type,
        countries_supported=("jp", "us"),
        generation_frequency="encounter_once",
        composition_sections=composition_sections,
        stage2_strategy="template_seed_bundle",
        llm_enabled_sections=llm_enabled_sections,
    )


def _bundle_template_output() -> NarrativeOutput:
    return NarrativeOutput(
        sections={
            "subjective": "S seed",
            "objective": "T 37.2 / HR 78 / SpO2 96",
            "assessment": "A seed",
            "plan": "P seed",
        },
        metadata={"generator": "template", "lang": "en"},
        facts_used=["ctx.day_index"],
    )


def test_bundle_strategy_makes_one_llm_call_per_document() -> None:
    """template_seed_bundle: even with 3 LLM-eligible sections, only ONE
    LLM call fires (per-doc bundle) instead of 3 per-section."""
    spec = _bundle_spec()
    provider = MockProvider()
    ctx = _make_ctx()

    result = _apply(_bundle_template_output(), ctx, spec, _mock_llm(provider))

    assert provider.call_count == 1  # single bundle call
    # All 3 target sections replaced
    for section in ("subjective", "assessment", "plan"):
        assert "[Mock LLM response" in result.sections[section]
    # `objective` (not in llm_enabled_sections) stays templated
    assert result.sections["objective"] == "T 37.2 / HR 78 / SpO2 96"


def test_bundle_strategy_prompt_lists_target_names_and_context_sections() -> None:
    """Bundle prompt carries target section NAMES (context-driven mode —
    template seeds are NOT leaked as a rewrite anchor) plus context
    sections with the structured facts the LLM must not contradict.

    Post-88j-v4 shift (Q): the prompt no longer includes template
    section bodies as "seeds". Instead the LLM is instructed to
    generate fresh narrative for each named section from the context
    facts. This test locks in that the prompt lists the section names
    and preserves the context section reveal.
    """
    spec = _bundle_spec()
    provider = MockProvider()
    ctx = _make_ctx()

    _apply(_bundle_template_output(), ctx, spec, _mock_llm(provider))

    prompt = provider.last_prompt
    # Target section names listed (as a JSON list, not name→seed dict).
    assert '"subjective"' in prompt
    assert '"assessment"' in prompt
    assert '"plan"' in prompt
    # Template seed text is NOT leaked into the target-sections block.
    assert '"S seed"' not in prompt
    assert '"A seed"' not in prompt
    assert '"P seed"' not in prompt
    # Context still includes the untouched structured section (Objective).
    assert '"objective": "T 37.2 / HR 78 / SpO2 96"' in prompt
    # Contract keywords
    assert "Context sections" in prompt or "reference only" in prompt.lower()


def test_bundle_strategy_falls_back_to_per_section_on_bad_json() -> None:
    """If the provider returns non-JSON (contract violation), the strategy
    falls back to per-section replacement so quality never regresses to
    template silently."""

    class _NonJsonProvider(MockProvider):
        def complete(self, prompt, **kw):  # type: ignore[override]
            self.call_count += 1
            # Ignore the bundle contract — return bare text.
            from clinosim.modules.llm_service.providers.base import ProviderResponse

            return ProviderResponse(
                text="Not a JSON object — plain narrative reply.",
                input_tokens=10,
                output_tokens=10,
                model="mock",
                latency_ms=0,
            )

    spec = _bundle_spec()
    provider = _NonJsonProvider()
    ctx = _make_ctx()

    result = _apply(_bundle_template_output(), ctx, spec, _mock_llm(provider))

    # 1 bundle call + N per-section retries = 4 total (bundle fell back)
    assert provider.call_count == 1 + len(spec.llm_enabled_sections)
    # Sections still populated via per-section fallback
    for section in ("subjective", "assessment", "plan"):
        assert "Not a JSON" in result.sections[section] or "reply" in result.sections[section]


def test_bundle_strategy_free_text_rebuilds_raw_text() -> None:
    """FREE_TEXT bundle (progress_note): after one bundle call replaces
    the S/A/P sections, `raw_text` is rebuilt from sections using the
    template's `raw_text_rejoin` metadata."""
    spec = _bundle_spec(
        format_type=FormatType.FREE_TEXT,
        type_key="progress_note",
    )
    labels = [("S:", "subjective"), ("O:", "objective"), ("A:", "assessment"), ("P:", "plan")]
    sections = {
        "subjective": "S seed",
        "objective": "T 37.2",
        "assessment": "A seed",
        "plan": "P seed",
    }
    template_output = NarrativeOutput(
        raw_text="\n".join(f"{label} {sections[key]}" for label, key in labels),
        sections=sections,
        metadata={
            "generator": "template",
            "lang": "en",
            "raw_text_rejoin": {"separator": "\n", "order": labels},
        },
        facts_used=["ctx.day_index"],
    )
    provider = MockProvider()
    ctx = _make_ctx()

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    assert provider.call_count == 1
    # raw_text rebuilt with LLM sections + template objective
    assert result.raw_text.startswith("S: [Mock LLM response")
    assert "O: T 37.2" in result.raw_text
    assert "A: [Mock LLM response" in result.raw_text
    assert "P: [Mock LLM response" in result.raw_text


def test_bundle_strategy_cache_hit_reuses_bundle_across_patients() -> None:
    """Bundle cache key hashes ALL seed sections together so identical
    (disease, day, severity, bundle-seeds) tuples across patients share
    ONE LLM call."""
    from clinosim.modules.document.narrative.cache import NarrativeCache

    cache = NarrativeCache()
    spec = _bundle_spec()
    provider = MockProvider()
    llm = _mock_llm(provider)

    ctx_a = _make_ctx()
    ctx_a.patient = {"age": 55, "sex": "M"}
    ctx_b = _make_ctx()
    ctx_b.patient = {"age": 57, "sex": "M"}  # same 50s-M bucket

    shared = {
        "subjective": "identical S seed",
        "objective": "T 37.2",
        "assessment": "identical A seed",
        "plan": "identical P seed",
    }
    o_a = NarrativeOutput(sections=dict(shared), metadata={}, facts_used=[])
    o_b = NarrativeOutput(sections=dict(shared), metadata={}, facts_used=[])

    _apply(o_a, ctx_a, spec, llm, cache_get=cache.get, cache_put=cache.put)
    _apply(o_b, ctx_b, spec, llm, cache_get=cache.get, cache_put=cache.put)

    # Second doc hits the cache — total LLM calls stays at 1
    assert provider.call_count == 1


def test_bundle_strategy_empty_llm_sections_returns_template_unchanged() -> None:
    """Empty llm_enabled_sections (validator-invalid production-side, but
    defensively supported): no LLM call, template output returned."""
    spec = _bundle_spec(llm_enabled_sections=())
    provider = MockProvider()
    ctx = _make_ctx()

    result = _apply(_bundle_template_output(), ctx, spec, _mock_llm(provider))

    assert provider.call_count == 0
    assert result.sections == _bundle_template_output().sections


# ─────────────────────────────────────────────────────────────────
# v6 (2026-08-16) — inpatient blocker fix context enrichment
# ─────────────────────────────────────────────────────────────────


def _admission_spec():
    return _bundle_spec(
        type_key="admission_hp",
        llm_enabled_sections=("hpi", "assessment_and_plan"),
    )


def test_build_extra_context_surfaces_complications() -> None:
    """v6: complications_during_stay MUST appear when
    NarrativeContext.complications_occurred is non-empty."""
    from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context

    ctx = _make_ctx()
    ctx.complications_occurred = ["pneumothorax", "aspiration_pneumonia"]
    extra = _build_extra_context(ctx, _admission_spec(), template_section_names=set())
    assert "complications_during_stay" in extra
    assert "pneumothorax" in extra["complications_during_stay"]
    assert "aspiration_pneumonia" in extra["complications_during_stay"]


def test_build_extra_context_omits_complications_when_empty() -> None:
    """Empty complications_occurred → key omitted (kept payload small)."""
    from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context

    ctx = _make_ctx()
    ctx.complications_occurred = []
    extra = _build_extra_context(ctx, _admission_spec(), template_section_names=set())
    assert "complications_during_stay" not in extra


def test_build_extra_context_localizes_encounter_type_ja() -> None:
    """v6 localization: encounter_type raw enum → JA label for
    target_lang=ja. Fixes POP-000094 (外来 narrated as 「緊急入院」)."""
    from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context

    ctx = _make_ctx()
    ctx.encounter_type = SimpleNamespace(value="outpatient")
    ctx.target_lang = "ja"
    extra = _build_extra_context(ctx, _admission_spec(), template_section_names=set())
    assert extra.get("encounter_type") == "外来"


def test_build_extra_context_keeps_encounter_type_raw_for_en() -> None:
    """Non-JA locales receive the raw lowercased enum value."""
    from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context

    ctx = _make_ctx()
    ctx.encounter_type = SimpleNamespace(value="outpatient")
    ctx.target_lang = "en"
    extra = _build_extra_context(ctx, _admission_spec(), template_section_names=set())
    assert extra.get("encounter_type") == "outpatient"


def test_build_extra_context_supplemental_oxygen_flag() -> None:
    """v6: supplemental_oxygen_today MUST surface when today's vitals
    record on_supplemental_oxygen=True. Prevents "SpO2 89% だが酸素投与
    なしで安定" self-contradiction (POP-000075 doc-06)."""
    from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context

    ctx = _make_ctx()
    ctx.document_type = DocumentType.PROGRESS_NOTE
    ctx.encounter = SimpleNamespace(admission_datetime="2026-03-28T00:00:00")
    ctx.vitals = [
        SimpleNamespace(
            timestamp="2026-03-28T10:00:00",
            on_supplemental_oxygen=True,
            oxygen_delivery_device="nasal cannula",
            oxygen_flow_rate_lpm=2.0,
            day=None,
            spo2=89.0,
        )
    ]
    ctx.day_index = 0
    spec = _bundle_spec(
        type_key="progress_note",
        llm_enabled_sections=("subjective", "assessment", "plan"),
    )
    extra = _build_extra_context(ctx, spec, template_section_names=set())
    assert extra.get("supplemental_oxygen_today", "").startswith("nasal cannula")
    assert "L/min" in extra["supplemental_oxygen_today"]


def test_build_extra_context_abnormal_labs_today_filters_by_flag() -> None:
    """Only H/L/critical-flagged labs are surfaced — stable results are
    intentionally omitted to keep the payload focused."""
    from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context

    ctx = _make_ctx()
    ctx.document_type = DocumentType.PROGRESS_NOTE
    ctx.day_index = 0
    ctx.lab_results = [
        SimpleNamespace(lab_name="AST", value=180, unit="U/L", flag="H", day=0),
        SimpleNamespace(lab_name="ALT", value=25, unit="U/L", flag=None, day=0),
        SimpleNamespace(lab_name="Cr", value=2.4, unit="mg/dL", flag="H", day=0),
    ]
    spec = _bundle_spec(
        type_key="progress_note",
        llm_enabled_sections=("subjective", "assessment", "plan"),
    )
    extra = _build_extra_context(ctx, spec, template_section_names=set())
    labs = extra.get("abnormal_labs_today", "")
    assert "AST" in labs and "[H]" in labs
    assert "Cr" in labs
    # unflagged ALT is intentionally excluded
    assert "ALT 25" not in labs


def test_build_extra_context_discharge_summary_enrichment() -> None:
    """v6: discharge_summary MUST receive complications_during_stay,
    abnormal_labs_during_stay, key_procedures_performed, and
    vitals_range_during_stay so LLM has per-patient facts to compose
    hospital_course from."""
    from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context

    ctx = _make_ctx()
    ctx.document_type = DocumentType.DISCHARGE_SUMMARY
    ctx.complications_occurred = ["pneumothorax"]
    ctx.procedures = [SimpleNamespace(procedure_name="chest tube insertion", day=3)]
    ctx.lab_results = [SimpleNamespace(lab_name="WBC", value=18.2, unit="10^9/L", flag="H", day=1)]
    ctx.vitals = [
        SimpleNamespace(
            temperature_celsius=39.2, systolic_bp=90, spo2=88, heart_rate=120, day=None, timestamp="2026-03-28T00:00:00"
        ),
        SimpleNamespace(
            temperature_celsius=36.9, systolic_bp=120, spo2=97, heart_rate=76, day=None, timestamp="2026-04-05T00:00:00"
        ),
    ]
    spec = _bundle_spec(
        type_key="discharge_summary",
        llm_enabled_sections=("hospital_course", "discharge_instructions"),
    )
    extra = _build_extra_context(ctx, spec, template_section_names=set())
    assert "pneumothorax" in extra.get("complications_during_stay", "")
    assert "chest tube" in extra.get("key_procedures_performed", "").lower()
    assert "WBC" in extra.get("abnormal_labs_during_stay", "")
    range_line = extra.get("vitals_range_during_stay", "")
    assert "sBP" in range_line and "T" in range_line and "SpO2" in range_line
