"""Shipped LLM configs, cache and truncation reporting work as configured (Issue #2199)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.modules.llm_service.factory import build_from_config_file
from clinosim.modules.llm_service.providers.bedrock import BedrockProvider
from clinosim.modules.llm_service.providers.ollama import OllamaProvider

pytestmark = pytest.mark.unit

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "clinosim" / "config"


@pytest.mark.parametrize("path", sorted(_CONFIG_DIR.glob("llm_service*.yaml")), ids=lambda p: p.name)
def test_every_shipped_config_builds(path: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # cache directories are relative to the working directory
    service = build_from_config_file(path)
    assert service is not None


def test_default_config_creates_a_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    service = build_from_config_file(_CONFIG_DIR / "llm_service.yaml")
    assert service.cache is not None and service.cache.enabled


def test_ollama_reports_truncation_as_length(monkeypatch) -> None:
    import httpx

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"response": "partial", "done_reason": "length", "eval_count": 9, "total_duration": 1}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    resp = OllamaProvider({"model": "m"}).complete("user", model="m", system_prompt="sys")
    assert resp.metadata["finish_reason"] == "length"


def test_bedrock_reports_truncation_as_length() -> None:
    class _Client:
        def converse(self, **_kwargs) -> dict:
            return {"output": {"message": {"content": [{"text": "partial"}]}}, "stopReason": "max_tokens", "usage": {}}

    provider = BedrockProvider({"model_id": "anthropic.test"})
    provider._client = _Client()
    resp = provider.complete("user", model="anthropic.test", system_prompt="sys")
    assert resp.metadata["finish_reason"] == "length"
