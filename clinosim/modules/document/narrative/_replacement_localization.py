"""Replacement-strategy localization helpers (JA).

First mechanical slice of the META #1633 P6 ``replacement_strategy``
decomposition (sibling to the ``template_generator`` → ``_localization.py``
split in #1671). The 12 helpers here cover severity / oxygen-device /
arrival-mode / risk-level / Barthel-band / lab-name token lookups
plus the LLM-output post-processors that walk emitted narrative text
and swap EN lab tokens for canonical JA katakana.

Zero behaviour change: ``replacement_strategy.py`` re-exports every
moved name via explicit ``from … import X as X`` aliases so external
callers (e.g. ``diagnostic_report.py``'s ``localize_lab_name`` import)
and tests see no API change.

Phase 1d-2 (2026-09-23): the vocab tables live in
``clinosim/locale/shared/llm_prompt_labels.yaml``; adding a new
target language is a data change, not a code change.
"""

from __future__ import annotations

import re


def _lookup_ja_label(raw: str, section: str) -> str:
    """Case-insensitive JA lookup for a raw enum-like token in the
    named LLM-prompt-labels section. Returns the raw input if the
    section / slug / ja slot is missing (safe fallback — never drops
    content). Kept named ``_lookup_ja_label`` because every caller
    below resolves against the ``ja`` slot; multi-lang callers use
    ``_localize_token`` which routes through
    ``resolve_localized_display`` (language-agnostic)."""
    if not raw:
        return raw
    key = str(raw).strip().lower()
    from clinosim.locale.loader import load_llm_prompt_labels, resolve_localized_display

    return resolve_localized_display(
        load_llm_prompt_labels().get(section, {}).get(key, {}),
        "ja",
        fallback=str(raw),
    )


def _localize_severity_ja(sev: str) -> str:
    """mild → 軽度 (etc). Safe fallback returns input verbatim."""
    return _lookup_ja_label(sev, "severity")


def _localize_oxygen_device_ja(device: str) -> str:
    """nasal_cannula → 経鼻カニューレ (etc)."""
    return _lookup_ja_label(device, "oxygen_device")


def _localize_arrival_mode_ja(mode: str) -> str:
    """walk_in → 独歩来院 (etc)."""
    return _lookup_ja_label(mode, "arrival_mode")


def _localize_risk_level_ja(level: str) -> str:
    """moderate_risk → 中等度リスク (etc)."""
    return _lookup_ja_label(level, "risk_level")


def _localize_barthel_band_ja(band: str) -> str:
    """barthel_full → Barthel 自立 (etc)."""
    return _lookup_ja_label(band, "barthel_band")


def _localize_lab_name_ja(name: str) -> str:
    """Creatinine → クレアチニン. Keeps abbreviations (BUN, CRP, WBC)
    as-is since they are Japanese medical standard."""
    if not name:
        return name
    return _lookup_ja_label(name, "lab_name")


def localize_lab_name(name: str, lang: str) -> str:
    """Language-aware lab-name localizer wrapper. No-op when
    ``lang != "ja"``. Callers that used to gate on
    ``if lang == "ja":`` around ``_localize_lab_name_ja`` can call
    this unconditionally instead — adding a new locale means
    extending ``llm_prompt_labels.yaml/lab_name:`` with the new
    ``<lang>`` slot (data-only change)."""
    if not name or lang != "ja":
        return name
    return _localize_lab_name_ja(name)


def localize_oxygen_device(device: str, lang: str) -> str:
    """Language-aware oxygen-device localizer wrapper (sibling to
    ``localize_lab_name``). No-op when ``lang != "ja"``."""
    if not device or lang != "ja":
        return device
    return _localize_oxygen_device_ja(device)


# --- prompt v11: post-processor hard-guard for EN lab names in JA text ------
# LLM occasionally emits full-English lab names verbatim in JA narrative
# output even after Rule 5 D of the prompt asks for canonical Japanese
# translations (Albumin 4.0 g/dL, Creatinine 1.2 mg/dL, …). The hard
# guard below is a deterministic post-processor that walks the LLM
# output and swaps EN lab NAMES for canonical JA katakana, preserving
# numeric value + unit verbatim. Standard abbreviations (BUN, CRP, BNP,
# WBC, HbA1c, eGFR, Cr, PT-INR, …) are kept as-is per the YAML's
# deliberate omission comment.
# Compound names ("Total bilirubin", "Direct bilirubin", "Total protein",
# "Urea nitrogen", "White blood cell", "Red blood cell", "Troponin I/T")
# are matched BEFORE their single-word bases via longest-first ordering.
# Phase 1d-2 (2026-09-23): lazy-compiled longest-first regex over the
# ``lab_name`` section of ``llm_prompt_labels.yaml``. The pattern must
# recompile if the YAML changes; ``functools.lru_cache`` on
# ``load_llm_prompt_labels`` guarantees a stable dict identity for the
# process lifetime, so caching on that identity is safe.
_LAB_NAME_PATTERN_CACHE: dict[int, re.Pattern[str]] = {}


def _get_lab_name_pattern() -> re.Pattern[str]:
    from clinosim.locale.loader import load_llm_prompt_labels

    section = load_llm_prompt_labels().get("lab_name", {})
    cache_key = id(section)
    hit = _LAB_NAME_PATTERN_CACHE.get(cache_key)
    if hit is not None:
        return hit
    keys = sorted(section.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b",
        re.IGNORECASE,
    )
    _LAB_NAME_PATTERN_CACHE[cache_key] = pattern
    return pattern


def _localize_lab_names_in_text_ja(text: str) -> str:
    """Post-process narrative text: substitute English lab names with
    canonical Japanese katakana. Deterministic; safe on non-JA text
    (only substitutes strings that appear in the JA table). Preserves
    the surrounding text verbatim — only the matched lab-name token is
    replaced.
    """
    if not text:
        return text

    def _repl(m: re.Match) -> str:
        return _lookup_ja_label(m.group(1), "lab_name")

    return _get_lab_name_pattern().sub(_repl, text)


def _localize_lab_names_in_sections_ja(sections: dict[str, str]) -> dict[str, str]:
    """Apply the text-level lab-name post-processor to every section
    value. Returns a NEW dict; leaves the input untouched so caller
    replacement is explicit at the call site.
    """
    return {k: _localize_lab_names_in_text_ja(v) for k, v in sections.items()}
