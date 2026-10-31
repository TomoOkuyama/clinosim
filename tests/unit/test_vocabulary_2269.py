"""Issue #2269: one display table per vocabulary (occupation, smoking,
alcohol, arrival mode) for FHIR, narrative templates and LLM prompts."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.locale.loader import load_vocabulary, narrative_label, vocab_display
from clinosim.modules.document.narrative._patient_info_renderers import _localize_token
from clinosim.modules.document.narrative._replacement_localization import _localize_arrival_mode_ja
from clinosim.modules.document.narrative._template_helpers import _label
from clinosim.modules.newborn.fhir_emit import _label as newborn_label
from clinosim.modules.output.fhir_r4.demographics.patient import _build_occupation_observation

pytestmark = pytest.mark.unit

_LOCALE = Path(__file__).resolve().parents[2] / "clinosim" / "locale"
_VOCABS = ("occupation", "smoking", "alcohol", "arrival_mode")


def _generated_occupations() -> set[str]:
    slugs = {"infant", "preschool", "elementary_student", "middle_school_student", "student", "retired"}
    for country in ("us", "jp"):
        demo = yaml.safe_load((_LOCALE / country / "demographics.yaml").read_text(encoding="utf-8"))
        cfg = demo.get("occupation_distribution") or {}
        for value in cfg.values():
            if isinstance(value, dict):
                for inner in value.values():
                    if isinstance(inner, dict):
                        slugs |= {k for k, v in inner.items() if isinstance(v, (int, float))}
                slugs |= {
                    k for k, v in value.items() if isinstance(v, (int, float)) and not k.endswith(("_age", "_prob"))
                }
    return slugs


def test_every_vocabulary_entry_has_en_and_ja() -> None:
    for vocab in _VOCABS:
        for slug, entry in load_vocabulary()[vocab].items():
            assert entry.get("en") and entry.get("ja"), (vocab, slug)


def test_every_generated_occupation_is_in_the_table() -> None:
    table = load_vocabulary()["occupation"]
    missing = sorted(s for s in _generated_occupations() if s not in table)
    assert not missing, missing


@pytest.mark.parametrize("vocab", _VOCABS)
@pytest.mark.parametrize("lang", ["ja", "en"])
def test_narrative_llm_and_fhir_show_the_same_string(vocab: str, lang: str) -> None:
    for slug in load_vocabulary()[vocab]:
        expected = vocab_display(vocab, slug, lang)
        assert _label(vocab, slug, lang) == expected
        assert newborn_label(vocab, slug, lang) == expected
        assert narrative_label(vocab, slug, lang) == expected
        if slug not in ("unknown", "none"):  # the LLM renderer omits these on purpose
            # The LLM anchor is running prose: same label, leading capital lowered.
            assert _localize_token(slug, vocab, lang).casefold() == expected.casefold()
        if vocab == "arrival_mode" and lang == "ja":
            assert _localize_arrival_mode_ja(slug) == expected
        if vocab == "occupation":
            obs = _build_occupation_observation(slug, "p1", "JP" if lang == "ja" else "US")
            assert obs is not None and expected in str(obs)


def test_measured_divergences_are_gone() -> None:
    assert vocab_display("occupation", "office", "ja") == "事務職"
    assert vocab_display("occupation", "healthcare", "ja") == "医療従事者"
    assert vocab_display("smoking", "never", "ja") == vocab_display("smoking", "never_smoker", "ja")
    assert (
        vocab_display("arrival_mode", "walk-in", "ja") == vocab_display("arrival_mode", "walk_in", "ja") == "独歩来院"
    )
