"""Deterministic narrative cache (Tier 1 #3 α-min-1 PR1 Task 7, Idea E).

Cache key = hash(disease + archetype + day + severity + demographics_bucket + lang + section).
In-memory only; no eviction — flushed on process exit (session-lifetime cache).
In-process LRU replay: same context inputs → identical hash → no LLM re-call.

Two-layer cache design (N-chain, 2026-07-02):

- ``NarrativeCache`` (THIS module) = layer 1: in-memory, clinical-context key.
  Enables cross-patient reuse — two patients in the same clinical bucket share
  one generated section without even rendering a prompt.
- ``clinosim.modules.llm_service.cache.PromptCache`` = layer 2: on-disk,
  sha256(system+user+model) key inside ``LLMService``. Survives process
  restarts and dedupes exact prompt repeats across runs (cloud cost control).

The layers are complementary, not duplicates: layer 1 fires before prompt
construction (coarse clinical key), layer 2 fires after (exact prompt key).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def cache_key(
    disease: str,
    archetype: str,
    day_index: int,
    severity: str,
    demographics_bucket: str,
    lang: str,
    section: str = "",
) -> str:
    """Deterministic hash key from narrative context attributes.

    All inputs are serialized to JSON with sorted keys to guarantee
    byte-identical output regardless of dict-insertion order.
    """
    payload = json.dumps(
        {
            "disease": disease,
            "archetype": archetype,
            "day": day_index,
            "severity": severity,
            "demographics": demographics_bucket,
            "lang": lang,
            "section": section,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def demographics_bucket(patient: Any) -> str:
    """Coarse demographic bucket for cache key dimensionality.

    Formula: ``f"{age // 10}0s-{sex}"`` where age and sex come from the
    patient object via attribute access. Example: age=55, sex="M" → "50s-M".

    This is intentionally coarse — the purpose is to avoid serving identical
    cache entries to a 25-year-old and a 75-year-old patient. It is NOT used
    for clinical stratification.
    """
    age: int = getattr(patient, "age", 0)
    sex: str = getattr(patient, "sex", "U")
    decade = (age // 10) * 10
    return f"{decade}s-{sex}"


class NarrativeCache:
    """In-memory cache for LLM-generated narrative sections.

    No eviction policy: entries accumulate for the lifetime of the process
    (session cache). Call ``clear()`` between simulation runs if memory is a
    concern or when forcing a full regeneration.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        """Return cached value for key, or None on cache miss."""
        return self._store.get(key)

    def put(self, key: str, value: str) -> None:
        """Store value under key."""
        self._store[key] = value

    def clear(self) -> None:
        """Flush all cached values."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# Module-level default cache shared across the process; tests can instantiate
# their own NarrativeCache instances for isolation.
_default_cache = NarrativeCache()


def get_default_cache() -> NarrativeCache:
    """Return the module-level default NarrativeCache singleton."""
    return _default_cache
