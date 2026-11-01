"""Replacement-strategy localization helpers (JA).

First mechanical slice of the META #1633 P6 ``replacement_strategy``
decomposition (sibling to the ``template_generator`` → ``_localization.py``
split in #1671). The 12 helpers here cover severity / oxygen-device /
arrival-mode / risk-level / Barthel-band token lookups
plus the LLM-output post-processors that walk emitted narrative text
and swap EN lab tokens for canonical JA katakana.

``replacement_strategy.py`` re-exports every moved name via explicit
``from … import X as X`` aliases. Lab names resolve through
``clinosim.locale.loader.lab_display`` (Issue #2267).

Phase 1d-2 (2026-09-23): the vocab tables live in
``clinosim/locale/shared/llm_prompt_labels.yaml``; adding a new
target language is a data change, not a code change.
"""

from __future__ import annotations

import re
from functools import lru_cache


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


def localize_oxygen_device(device: str, lang: str) -> str:
    """Language-aware oxygen-device localizer wrapper. No-op when
    ``lang != "ja"``."""
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
# The guard's vocabulary is the English prose names in the shared lab
# display table (`locale/shared/lab_display.yaml`, Issue #2267) that are
# common nouns — lower-case words, optionally ending in one capital or
# number token ("troponin I", "vitamin B12") — and whose Japanese name
# differs. Abbreviations (BUN, CRP, Cr, HbA1c, ...) are not words, so they
# are kept as written, as Japanese clinicians write them.
_PROSE_LAB_TERM = re.compile(r"[a-z][a-z ]*[a-z](?: [A-Z0-9]+)?")


@lru_cache(maxsize=1)
def _lab_prose_terms_ja() -> dict[str, str]:
    from clinosim.locale.loader import load_lab_display

    terms: dict[str, str] = {}
    for entry in load_lab_display().values():
        en, ja = str(entry.get("en") or ""), str(entry.get("ja") or "")
        if ja and ja != en and _PROSE_LAB_TERM.fullmatch(en):
            terms.setdefault(en.lower(), ja)
    return terms


@lru_cache(maxsize=1)
def _get_lab_name_pattern() -> re.Pattern[str]:
    keys = sorted(_lab_prose_terms_ja(), key=len, reverse=True)
    return re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b",
        re.IGNORECASE,
    )


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
        return _lab_prose_terms_ja()[m.group(1).lower()]

    return _get_lab_name_pattern().sub(_repl, text)


def _localize_lab_names_in_sections_ja(sections: dict[str, str]) -> dict[str, str]:
    """Apply the text-level lab-name post-processor to every section
    value. Returns a NEW dict; leaves the input untouched so caller
    replacement is explicit at the call site.
    """
    return {k: _localize_lab_names_in_text_ja(v) for k, v in sections.items()}
