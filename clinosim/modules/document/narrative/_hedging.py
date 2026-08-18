"""Narrative-template hedging helper (2026-08-17 density improvement).

Enforces the design principle **Template = adequate density on its own /
LLM = optional quality enhancement**: when a template references
SCENARIO-derived (未確定) information — expected symptoms, typical
trajectory, differential — the text MUST be softened to avoid asserting
scenario as fact. Only CIF-CONFIRMED data (measured labs, actual
medications, recorded observations) is asserted plainly.

Loaded from ``clinosim/modules/document/reference_data/hedging_phrases.yaml``.
Callers reach for :func:`hedged_phrase` — one shot in, one string out.
"""

from __future__ import annotations

import random
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

_REGISTRY_PACKAGE = "clinosim.modules.document.reference_data"
_REGISTRY_FILENAME = "hedging_phrases.yaml"


@lru_cache(maxsize=1)
def _load_registry() -> dict[str, Any]:
    """Load the YAML registry once and cache it (small file, static shape)."""
    with resources.files(_REGISTRY_PACKAGE).joinpath(_REGISTRY_FILENAME).open("r") as f:
        return yaml.safe_load(f) or {}


def hedged_phrase(
    topic: str,
    value: str,
    *,
    confirmed: bool,
    lang: str = "ja",
    rng: random.Random | None = None,
    **placeholders: str,
) -> str:
    """Return one hedging phrase for ``topic`` with ``value`` interpolated.

    Args:
        topic: Registry key (``symptom`` / ``trajectory`` / ``lab_finding`` /
            ``treatment`` / ``complication`` / ``chronic_status``).
        value: Localized noun that fills the ``{value}`` placeholder.
        confirmed: True → assert plainly ("患者は X を訴える"). False →
            hedge ("本疾患で典型的な X は本日訴えなし"). This is the
            central switch that keeps scenario data from masquerading as
            fact when the CIF has no confirming record.
        lang: ``ja`` or ``en``. Falls back to ``ja`` when a language is
            unknown to keep the pipeline robust.
        rng: Optional deterministic RNG. Template renders are called from
            deterministic passes; when omitted, the first phrase in the
            registry list is used (stable across runs).
        **placeholders: Additional format placeholders (e.g.
            ``control="良好"`` for ``chronic_status``).

    Returns:
        A ready-to-emit string. Empty string when the topic / language /
        branch is unknown — callers can concatenate freely without
        introducing a broken half-sentence.
    """
    registry = _load_registry()
    entry = registry.get(topic) or {}
    branch = entry.get("confirmed" if confirmed else "unconfirmed") or {}
    phrases = branch.get(lang) or branch.get("ja") or []
    if not phrases:
        return ""
    if rng is not None:
        phrase = rng.choice(phrases)
    else:
        # Deterministic default: first entry. Template renders MUST be
        # deterministic across runs; call sites needing variation should
        # pass a seeded RNG (e.g. hashed on patient_id).
        phrase = phrases[0]
    subs = {"value": value, **placeholders}
    try:
        return phrase.format(**subs)
    except (KeyError, IndexError):
        # Missing placeholder in caller — return raw phrase rather than crash.
        return phrase.replace("{value}", value)


def has_topic(topic: str) -> bool:
    """True when ``topic`` is a valid registry key. Callers can guard
    lookups without triggering a fallback string."""
    return topic in _load_registry()
