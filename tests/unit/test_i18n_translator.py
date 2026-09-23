"""Unit tests for the Phase 1d-4 language-agnostic ``t(key, lang, **params)``
translator."""

from __future__ import annotations

from clinosim.locale.i18n import t


class TestChiefComplaint:
    """Chief-complaint phrase resolution."""

    def test_ja_encounter_reason(self) -> None:
        assert t("chief_complaint.encounter_reason", "ja", cc="発熱") == "来院理由: 発熱"

    def test_en_encounter_reason(self) -> None:
        assert t("chief_complaint.encounter_reason", "en", cc="fever") == "Encounter reason: fever"

    def test_fr_falls_back_to_en(self) -> None:
        # fr slot missing → en template used.
        assert t("chief_complaint.encounter_reason", "fr", cc="fièvre") == "Encounter reason: fièvre"

    def test_ja_primary_problem(self) -> None:
        assert t("chief_complaint.primary_problem", "ja", dx="心筋梗塞") == "主な問題: 心筋梗塞"

    def test_en_primary_problem(self) -> None:
        assert t("chief_complaint.primary_problem", "en", dx="MI") == "Primary problem: MI"


class TestProgress:
    """Progress-note phrase resolution."""

    def test_ja_stable_course_assessment(self) -> None:
        assert t("progress.stable_course_assessment", "ja") == "経過観察中、著変なし。"

    def test_en_stable_course_assessment(self) -> None:
        assert t("progress.stable_course_assessment", "en") == "Clinical course stable, no significant change."

    def test_ja_stable_course_plan(self) -> None:
        assert t("progress.stable_course_plan", "ja") == "治療継続"

    def test_ja_complications_noted(self) -> None:
        out = t("progress.complications_noted", "ja", list="せん妄、急性腎障害")
        assert out == "合併症 せん妄、急性腎障害 を認識、対応継続中。"

    def test_en_complications_noted(self) -> None:
        out = t("progress.complications_noted", "en", list="delirium, AKI")
        assert out == "Complications noted (delirium, AKI); management ongoing."

    def test_ja_notable_labs(self) -> None:
        out = t("progress.notable_labs", "ja", list="クレアチニン 3.2 mg/dL [重篤]")
        assert out == "本日の検査所見: クレアチニン 3.2 mg/dL [重篤]。"


class TestFallback:
    """Fallback / error-handling semantics."""

    def test_unknown_key_returns_key(self) -> None:
        # An unresolved dot-notation path echoes the key itself so callers
        # see something readable rather than an empty string.
        assert t("does.not.exist", "ja") == "does.not.exist"

    def test_missing_param_returns_raw_template(self) -> None:
        # Interpolation KeyError → return the raw template rather than
        # raising into the caller.
        assert t("chief_complaint.encounter_reason", "ja") == "来院理由: {cc}"

    def test_ja_slug_falls_back_to_en_when_missing_ja_slot(self) -> None:
        # ``resolve_localized_display`` fallback chain: entry[lang] →
        # entry[en] → fallback. Verified via the shared helper directly
        # since narrative_phrases.yaml intentionally carries both slots
        # for every entry.
        from clinosim.locale.loader import resolve_localized_display

        assert resolve_localized_display({"en": "hello"}, "ja", fallback="raw") == "hello"
        assert resolve_localized_display({"ja": "こんにちは"}, "en", fallback="raw") == "raw"

    def test_lang_case_insensitive(self) -> None:
        # ``resolve_localized_display`` lower-cases lang keys and treats
        # "JP" as an alias for "ja"; the translator inherits this.
        assert t("chief_complaint.encounter_reason", "JA", cc="発熱") == "来院理由: 発熱"
        assert t("chief_complaint.encounter_reason", "JP", cc="発熱") == "来院理由: 発熱"


class TestKeyResolution:
    """Dot-notation navigation."""

    def test_intermediate_branch_returns_key(self) -> None:
        # A branch node (dict of nested dicts) is not a leaf — the
        # translator returns the key rather than picking a random leaf.
        assert t("chief_complaint", "ja") == "chief_complaint"

    def test_missing_leaf_returns_key(self) -> None:
        assert t("chief_complaint.nonexistent", "ja") == "chief_complaint.nonexistent"
