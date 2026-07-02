"""Deterministic narrative cache (Tier 1 #3 α-min-1 PR1 Task 7, Idea E).

Cache key = hash(disease + archetype + day + severity + demographics_bucket
+ lang + section + seed_hash). The ``seed_hash`` component (sha256 of the
template seed text, N-chain adv-1 C-1) makes wrong-patient reuse structurally
impossible: a cache hit implies an identical template seed, while genuinely
identical seeds still enable cross-patient reuse.
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

from clinosim.modules._shared import get_attr_or_key


def template_seed_hash(template_text: str) -> str:
    """Short deterministic hash of a template seed text (C-1, N-chain adv-1).

    Used as the ``seed_hash`` component of :func:`cache_key`. 16 hex chars of
    sha256 — collision-safe at cohort scale while keeping keys compact.
    """
    return hashlib.sha256(template_text.encode()).hexdigest()[:16]


def cache_key(
    disease: str,
    archetype: str,
    day_index: int,
    severity: str,
    demographics_bucket: str,
    lang: str,
    section: str = "",
    seed_hash: str = "",
) -> str:
    """Deterministic hash key from narrative context attributes.

    All inputs are serialized to JSON with sorted keys to guarantee
    byte-identical output regardless of dict-insertion order.

    ``seed_hash`` (C-1, N-chain adv-1) is a hash of the template seed text
    supplied by ``_apply_template_seed_strategy`` (see
    :func:`template_seed_hash`). Including it makes a cache hit equivalent to
    "identical seed": two patients only share an entry when their template
    seeds genuinely match, so wrong-patient narrative reuse is structurally
    impossible even if the clinical-context components degenerate.
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
            "seed_hash": seed_hash,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def demographics_bucket(patient: Any) -> str:
    """Coarse demographic bucket for cache key dimensionality.

    Formula: ``f"{age // 10}0s-{sex}"``. Example: age=55, sex="M" → "50s-M".

    C-1 (N-chain adv-1): age/sex are read via ``get_attr_or_key`` (dict +
    dataclass dual access, repo rule) — the production ``NarrativePass``
    supplies ``ctx.patient`` as a JSON-deserialized dict, and plain
    ``getattr`` silently bucketed EVERY patient to "0s-U" (cache key collapse
    → cross-patient narrative contamination risk).

    This is intentionally coarse — the purpose is to avoid serving identical
    cache entries to a 25-year-old and a 75-year-old patient. It is NOT used
    for clinical stratification.
    """
    age = int(get_attr_or_key(patient, "age", 0) or 0)
    sex = str(get_attr_or_key(patient, "sex", "U") or "U")
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
