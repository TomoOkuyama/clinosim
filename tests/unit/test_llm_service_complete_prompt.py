"""Tests for LLMService.complete_prompt (N-2, N-chain narrative IF unification).

complete_prompt is the single low-level public API for pre-built prompts:
retry + PromptCache + token accounting, NO template fallback — on provider
absence or retry exhaustion it raises LLMCompletionError and the CALLER
(e.g. LLMNarrativeGenerator) decides the fallback.
"""
from __future__ import annotations

import pytest

from clinosim.modules.llm_service.cache import PromptCache
from clinosim.modules.llm_service.engine import (
    LLMCompletionError,
    LLMService,
    LLMTaskType,
)
from clinosim.modules.llm_service.providers import MockProvider


class _RaisingProvider:
    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, prompt, model=None, max_tokens=1000, system_prompt="",
                 temperature=0.4, stop_sequences=None):
        self.call_count += 1
        raise ConnectionError("refused")

    def health_check(self) -> bool:
        return False


def _service(provider=None, cache=None, retry_attempts=2) -> LLMService:
    return LLMService(
        mode="llm",
        narrative_provider=provider if provider is not None else MockProvider(),
        narrative_model_map={"medium": "mock-medium"},
        provider_name_narrative="mock",
        cache=cache,
        retry_attempts=retry_attempts,
        retry_backoff_seconds=0.0,
    )


@pytest.mark.unit
def test_complete_prompt_returns_llm_response_with_text() -> None:
    svc = _service()
    resp = svc.complete_prompt(
        "system text", "user text",
        language="en", task_type=LLMTaskType.ADMISSION_HP,
    )
    assert resp.source == "llm"
    assert resp.text
    assert resp.provider == "mock"
    assert resp.model == "mock-medium"


@pytest.mark.unit
def test_complete_prompt_accounts_tokens_and_calls() -> None:
    svc = _service()
    svc.complete_prompt("s", "u one two three",
                        language="en", task_type=LLMTaskType.ADMISSION_HP)
    assert svc.call_count == 1
    assert svc.total_input_tokens > 0
    assert svc.total_output_tokens > 0


@pytest.mark.unit
def test_complete_prompt_no_provider_raises() -> None:
    svc = LLMService(mode="llm", narrative_provider=None)
    with pytest.raises(LLMCompletionError):
        svc.complete_prompt("s", "u", language="en",
                            task_type=LLMTaskType.ADMISSION_HP)


@pytest.mark.unit
def test_complete_prompt_retry_exhaustion_raises_no_template_fallback() -> None:
    provider = _RaisingProvider()
    svc = _service(provider=provider, retry_attempts=3)
    with pytest.raises(LLMCompletionError):
        svc.complete_prompt("s", "u", language="en",
                            task_type=LLMTaskType.ADMISSION_HP)
    assert provider.call_count == 3  # all retries attempted
    assert svc.fallback_count == 0  # NO template fallback in this API


@pytest.mark.unit
def test_complete_prompt_uses_prompt_cache(tmp_path) -> None:
    cache = PromptCache(cache_dir=tmp_path, enabled=True)
    provider = MockProvider()
    svc = _service(provider=provider, cache=cache)
    r1 = svc.complete_prompt("s", "u", language="en",
                             task_type=LLMTaskType.ADMISSION_HP)
    r2 = svc.complete_prompt("s", "u", language="en",
                             task_type=LLMTaskType.ADMISSION_HP)
    assert provider.call_count == 1  # second call served from disk cache
    assert r2.cache_hit is True
    assert r2.source == "cache"
    assert r2.text == r1.text
    assert svc.cache_hit_count == 1


@pytest.mark.unit
def test_complete_prompt_max_tokens_temperature_override() -> None:
    class _Capture(MockProvider):
        def complete(self, prompt, model=None, max_tokens=1000, system_prompt="",
                     temperature=0.4, stop_sequences=None):
            self.captured = (max_tokens, temperature)
            return super().complete(prompt, model, max_tokens, system_prompt,
                                    temperature, stop_sequences)

    provider = _Capture()
    svc = _service(provider=provider)
    svc.complete_prompt("s", "u", language="en",
                        task_type=LLMTaskType.ADMISSION_HP,
                        max_tokens=42, temperature=0.9)
    assert provider.captured == (42, 0.9)


@pytest.mark.unit
def test_complete_prompt_judgment_task_uses_judgment_provider() -> None:
    judgment = MockProvider()
    narrative = MockProvider()
    svc = LLMService(
        mode="llm",
        judgment_provider=judgment,
        narrative_provider=narrative,
        judgment_model_map={"medium": "judge-model"},
        narrative_model_map={"medium": "narr-model"},
        provider_name_judgment="judge",
        provider_name_narrative="narr",
        retry_attempts=1,
        retry_backoff_seconds=0.0,
    )
    resp = svc.complete_prompt("s", "u", language="en",
                               task_type=LLMTaskType.DIAGNOSTIC_REASONING)
    assert judgment.call_count == 1
    assert narrative.call_count == 0
    assert resp.provider == "judge"
