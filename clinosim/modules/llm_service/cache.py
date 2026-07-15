"""SHA256-keyed disk cache for LLM responses.

Purpose: when Stage 2 is re-run (e.g. after a failed narrate), identical
prompts should not re-invoke the LLM. Also supports reproducibility (AD-16):
two runs with the same seed and same prompts produce identical text.

Storage format: one JSON file per cached entry.
    <cache_dir>/<sha256 prefix>/<sha256>.json

Entry:
    {
      "text": "...",
      "input_tokens": 1250,
      "output_tokens": 480,
      "model": "anthropic.claude-...",
      "latency_ms": 0,
      "metadata": {...}
    }
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .providers.base import ProviderResponse


class PromptCache:
    """Content-addressed disk cache for LLM responses."""

    def __init__(
        self,
        cache_dir: str | Path | None,
        enabled: bool = True,
        max_entries: int = 100_000,
    ):
        self.enabled = bool(enabled and cache_dir)
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.dir: Path | None = Path(cache_dir) if cache_dir else None
        if self.enabled and self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hash(system: str, user: str, model: str) -> str:
        h = hashlib.sha256()
        h.update(b"SYS\x00")
        h.update(system.encode("utf-8"))
        h.update(b"\x00USER\x00")
        h.update(user.encode("utf-8"))
        h.update(b"\x00MODEL\x00")
        h.update(model.encode("utf-8"))
        return h.hexdigest()

    def _path_for(self, key: str) -> Path:
        assert self.dir is not None
        return self.dir / key[:2] / f"{key}.json"

    def get(self, system: str, user: str, model: str) -> ProviderResponse | None:
        if not self.enabled or self.dir is None:
            return None
        key = self._hash(system, user, model)
        path = self._path_for(key)
        if not path.exists():
            self.misses += 1
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.misses += 1
            return None
        self.hits += 1
        return ProviderResponse(
            text=data.get("text", ""),
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            model=data.get("model", model),
            latency_ms=int(data.get("latency_ms", 0)),
            metadata=data.get("metadata"),
        )

    def put(self, system: str, user: str, model: str, response: ProviderResponse) -> None:
        if not self.enabled or self.dir is None:
            return
        key = self._hash(system, user, model)
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "text": response.text,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "metadata": response.metadata or {},
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.writes += 1

    def stats(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "enabled": 1 if self.enabled else 0,
        }
