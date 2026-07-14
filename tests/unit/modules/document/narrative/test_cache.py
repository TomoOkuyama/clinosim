"""Tests for NarrativeCache and cache_key (Task 7, Tier 1 #3 α-min-1).

Tests cover:
- cache hit returns same value
- cache miss calls provider
- cache clear
- deterministic key generation (incl. seed_hash component, N-chain adv-1 C-1)
- demographics_bucket helper (dict + attribute dual access, C-1)
"""
from __future__ import annotations

from clinosim.modules.document.narrative.cache import (
    NarrativeCache,
    cache_key,
    demographics_bucket,
    get_default_cache,
    template_seed_hash,
)

# ─────────────────────────────────────────────────────────────────
# cache_key tests
# ─────────────────────────────────────────────────────────────────


def test_cache_deterministic_keys_same_inputs_same_hash() -> None:
    """Same inputs always produce identical hash."""
    key1 = cache_key(
        disease="bacterial_pneumonia",
        archetype="uncomplicated_improvement",
        day_index=2,
        severity="moderate",
        demographics_bucket="50s-M",
        lang="ja",
        section="hpi",
    )
    key2 = cache_key(
        disease="bacterial_pneumonia",
        archetype="uncomplicated_improvement",
        day_index=2,
        severity="moderate",
        demographics_bucket="50s-M",
        lang="ja",
        section="hpi",
    )
    assert key1 == key2


def test_cache_deterministic_keys_different_inputs_different_hash() -> None:
    """Different day_index produces different hash."""
    key_day2 = cache_key("d", "arch", 2, "moderate", "50s-M", "ja", "hpi")
    key_day3 = cache_key("d", "arch", 3, "moderate", "50s-M", "ja", "hpi")
    assert key_day2 != key_day3


def test_cache_deterministic_keys_different_section_different_hash() -> None:
    """Different section produces different hash."""
    key_hpi = cache_key("d", "arch", 0, "moderate", "50s-M", "ja", "hpi")
    key_ap = cache_key("d", "arch", 0, "moderate", "50s-M", "ja", "assessment_and_plan")
    assert key_hpi != key_ap


def test_cache_deterministic_keys_default_section_differs_from_named() -> None:
    """Omitting section (default '') differs from named section."""
    key_default = cache_key("d", "arch", 0, "moderate", "50s-M", "ja")
    key_named = cache_key("d", "arch", 0, "moderate", "50s-M", "ja", "hpi")
    assert key_default != key_named


def test_cache_key_different_seed_hash_different_key() -> None:
    """C-1: seed_hash is part of the key — different template seeds never collide."""
    key_a = cache_key(
        "d", "arch", 0, "moderate", "50s-M", "ja", "hpi",
        seed_hash=template_seed_hash("Patient A template text"),
    )
    key_b = cache_key(
        "d", "arch", 0, "moderate", "50s-M", "ja", "hpi",
        seed_hash=template_seed_hash("Patient B template text"),
    )
    assert key_a != key_b


def test_cache_key_same_seed_hash_same_key() -> None:
    """C-1: identical seeds (same clinical bucket) still enable cross-patient reuse."""
    h = template_seed_hash("Shared template text")
    key_1 = cache_key("d", "arch", 0, "moderate", "50s-M", "ja", "hpi", seed_hash=h)
    key_2 = cache_key("d", "arch", 0, "moderate", "50s-M", "ja", "hpi", seed_hash=h)
    assert key_1 == key_2


def test_template_seed_hash_deterministic_and_short() -> None:
    """template_seed_hash: deterministic, 16 hex chars, input-sensitive."""
    h1 = template_seed_hash("some text")
    h2 = template_seed_hash("some text")
    h3 = template_seed_hash("other text")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 16
    int(h1, 16)  # valid hex


# ─────────────────────────────────────────────────────────────────
# NarrativeCache tests
# ─────────────────────────────────────────────────────────────────


def test_cache_hit_returns_same_output_for_same_key() -> None:
    """Hash key collision returns cached value without re-generating."""
    cache = NarrativeCache()
    key = cache_key("bacterial_pneumonia", "arch", 0, "moderate", "50s-M", "ja", "hpi")
    cache.put(key, "cached narrative text")
    assert cache.get(key) == "cached narrative text"


def test_cache_miss_returns_none() -> None:
    """Key not in cache returns None (caller must invoke provider)."""
    cache = NarrativeCache()
    key = cache_key("unseen_disease", "arch", 0, "mild", "30s-F", "en", "hpi")
    assert cache.get(key) is None


def test_cache_miss_then_put_hit() -> None:
    """Put then get returns value (round-trip)."""
    cache = NarrativeCache()
    key = cache_key("disease_x", "arch_y", 1, "severe", "70s-M", "en")
    assert cache.get(key) is None
    cache.put(key, "generated text")
    assert cache.get(key) == "generated text"


def test_cache_clear_removes_all_entries() -> None:
    """clear() flushes all cached values."""
    cache = NarrativeCache()
    key1 = cache_key("d", "a", 0, "mild", "20s-M", "ja", "hpi")
    key2 = cache_key("d", "a", 1, "mild", "20s-M", "ja", "hpi")
    cache.put(key1, "text1")
    cache.put(key2, "text2")
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0
    assert cache.get(key1) is None
    assert cache.get(key2) is None


def test_cache_len_tracks_entries() -> None:
    """__len__ reflects the number of cached entries."""
    cache = NarrativeCache()
    assert len(cache) == 0
    cache.put("k1", "v1")
    assert len(cache) == 1
    cache.put("k2", "v2")
    assert len(cache) == 2


def test_get_default_cache_returns_singleton() -> None:
    """get_default_cache() always returns the same instance."""
    c1 = get_default_cache()
    c2 = get_default_cache()
    assert c1 is c2


# ─────────────────────────────────────────────────────────────────
# demographics_bucket helper
# ─────────────────────────────────────────────────────────────────


def test_demographics_bucket_decade_and_sex() -> None:
    """Bucket uses decade + sex."""
    from types import SimpleNamespace
    patient = SimpleNamespace(age=55, sex="M")
    bucket = demographics_bucket(patient)
    assert bucket == "50s-M"


def test_demographics_bucket_rounds_down_to_decade() -> None:
    """Ages within same decade share a bucket."""
    from types import SimpleNamespace
    p30 = SimpleNamespace(age=30, sex="F")
    p39 = SimpleNamespace(age=39, sex="F")
    assert demographics_bucket(p30) == demographics_bucket(p39) == "30s-F"


def test_demographics_bucket_different_ages_different_buckets() -> None:
    """Different decades produce different buckets."""
    from types import SimpleNamespace
    p20 = SimpleNamespace(age=25, sex="M")
    p30 = SimpleNamespace(age=35, sex="M")
    assert demographics_bucket(p20) != demographics_bucket(p30)


def test_demographics_bucket_dict_patient() -> None:
    """C-1 pin: production NarrativePass passes ctx.patient as a JSON dict.

    getattr on a dict always returns the default → every patient bucketed to
    "0s-U" and the layer-1 cache key collapsed to (lang, section) for the
    whole cohort. demographics_bucket must use dict/attribute dual access.
    """
    assert demographics_bucket({"age": 85, "sex": "M"}) == "80s-M"
    assert demographics_bucket({"age": 42, "sex": "F"}) == "40s-F"


def test_demographics_bucket_dict_missing_fields_defaults() -> None:
    """Dict patient with missing keys falls back to age=0 / sex='U'."""
    assert demographics_bucket({}) == "0s-U"
    assert demographics_bucket(None) == "0s-U"
