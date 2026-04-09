"""Factory to build LLMService instances from YAML config files.

See ``clinosim/config/llm_service.yaml`` for the expected schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .cache import PromptCache
from .engine import LLMService
from .prompt_registry import PromptRegistry
from .providers import build_provider


def build_from_config_file(path: str | Path) -> LLMService:
    """Load ``path`` and return a fully wired LLMService."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"LLM config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return build_from_config(data)


def build_from_config(config: dict[str, Any]) -> LLMService:
    """Build an LLMService from an already-parsed config dict."""
    judgment_cfg = config.get("judgment", {}) or {}
    narrative_cfg = config.get("narrative", {}) or {}
    cache_cfg = config.get("cache", {}) or {}
    prompts_cfg = config.get("prompts", {}) or {}

    judgment_provider = _build_provider_from_section(judgment_cfg)
    narrative_provider = _build_provider_from_section(narrative_cfg)

    # Mode defaults to narrative section's mode (narrative is the primary
    # consumer for document generation in Milestone 1)
    mode = narrative_cfg.get("mode") or judgment_cfg.get("mode") or "template"

    # PromptRegistry (optional custom path)
    registry_path = prompts_cfg.get("registry_path")
    registry = PromptRegistry(Path(registry_path)) if registry_path else PromptRegistry()

    # Cache
    cache: PromptCache | None = None
    if cache_cfg.get("enabled", True):
        cache_dir = cache_cfg.get("directory") or cache_cfg.get("cache_dir")
        if cache_dir:
            cache = PromptCache(
                cache_dir=cache_dir,
                enabled=True,
                max_entries=int(cache_cfg.get("max_entries", 100_000)),
            )

    return LLMService(
        mode=mode,
        judgment_provider=judgment_provider,
        narrative_provider=narrative_provider,
        judgment_model_map=judgment_cfg.get("model_map", {}) or {},
        narrative_model_map=narrative_cfg.get("model_map", {}) or {},
        prompt_registry=registry,
        cache=cache,
        retry_attempts=int(narrative_cfg.get("retry_attempts", 3)),
        retry_backoff_seconds=float(
            narrative_cfg.get("retry_backoff_seconds", 1.0)
        ),
        provider_name_judgment=judgment_cfg.get("provider", ""),
        provider_name_narrative=narrative_cfg.get("provider", ""),
    )


def _build_provider_from_section(section: dict[str, Any]) -> Any:
    """Given a judgment/narrative section dict, instantiate its provider.

    The section structure is:

        provider: "bedrock"            # registry key
        mode: "llm"                     # informational (service-level)
        bedrock:                        # provider-specific sub-block
          region: "us-east-1"
          model_id: "..."
        model_map: {...}

    Returns None if ``provider`` is missing/empty or mode == "template"/"none".
    """
    provider_name = section.get("provider", "")
    mode = section.get("mode", "")
    if not provider_name:
        return None
    if mode in ("template", "none"):
        # Provider is configured but service will use templates → still build
        # it? We opt for None here so template mode never touches the network.
        return None
    # The sub-block has the same name as the provider key
    provider_config = section.get(provider_name, {}) or {}
    return build_provider(provider_name, provider_config)
