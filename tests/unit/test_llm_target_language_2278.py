"""LLM prompts take the target-language name and instructions from one place (Issue #2278)."""

from __future__ import annotations

import pytest

from clinosim.countries import lang_name
from clinosim.modules.llm_service.engine import _output_language_instruction

pytestmark = pytest.mark.unit


def test_language_names_in_the_prompt_language() -> None:
    assert lang_name("ja") == "日本語"
    assert lang_name("en") == "English"
    assert lang_name("ja", in_lang="en") == "Japanese"


def test_unregistered_language_falls_back_to_english() -> None:
    assert lang_name("fr") == "English"


def test_instruction_is_written_in_the_target_language() -> None:
    assert "日本語" in _output_language_instruction("ja")
    assert _output_language_instruction("en").startswith("Write in English")
    assert _output_language_instruction("fr") == _output_language_instruction("en")
