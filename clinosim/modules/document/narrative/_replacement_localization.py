"""Replacement-strategy localization helpers.

First mechanical slice of the META #1633 P6 ``replacement_strategy``
decomposition (sibling to the ``template_generator`` → ``_localization.py``
split in #1671). The helpers here cover enum-like token lookups (severity /
oxygen device / arrival mode / risk level / Barthel band) in the document
language, plus the LLM-output post-processor that walks emitted narrative
text and swaps English prose lab names for their names in that language.

``replacement_strategy.py`` re-exports every moved name via explicit
``from … import X as X`` aliases. Lab names resolve through
``clinosim.locale.loader.lab_display`` (Issue #2267).

Phase 1d-2 (2026-09-23): the vocab tables live in
``clinosim/locale/shared/llm_prompt_labels.yaml``; adding a new
target language is a data change, not a code change. Every helper takes
the language; none is fixed to Japanese (Issue #3196).
"""

from __future__ import annotations

import re
from functools import cache


def localize_token(raw: str, section: str, lang: str) -> str:
    """``raw`` (an enum-like token) in ``lang`` from an LLM-prompt-labels
    section; the raw input when the section has no entry for ``lang`` (or
    English). Selects by data, never by comparing ``lang`` (Issue #2456)."""
    if not raw:
        return raw
    from clinosim.locale.loader import prompt_label

    return prompt_label(section, raw, lang, fallback=str(raw))


def localize_oxygen_device(device: str, lang: str) -> str:
    """Oxygen-device label in ``lang`` (then English): ``oxygen_device_label``
    — the label the FHIR device concept carries in ``text`` (Issue #3023) —
    else the text as given (a free-text term). No language branch of its
    own (Issue #2396)."""
    if not device:
        return device
    from clinosim.locale.loader import oxygen_device_label

    return oxygen_device_label(device, lang) or device


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


@cache
def _lab_prose_terms(lang: str) -> dict[str, str]:
    """English prose lab name (lower-cased) -> its name in ``lang``, for the
    names whose ``lang`` entry differs from the English one."""
    from clinosim.locale.loader import load_lab_display
    from clinosim.locale.localized import normalize_lang

    code = normalize_lang(lang)
    terms: dict[str, str] = {}
    for entry in load_lab_display().values():
        en, local = str(entry.get("en") or ""), str(entry.get(code) or "")
        if local and local != en and _PROSE_LAB_TERM.fullmatch(en):
            terms.setdefault(en.lower(), local)
    return terms


@cache
def _get_lab_name_pattern(lang: str) -> re.Pattern[str] | None:
    keys = sorted(_lab_prose_terms(lang), key=len, reverse=True)
    if not keys:
        return None
    return re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b",
        re.IGNORECASE,
    )


def localize_lab_names_in_text(text: str, lang: str) -> str:
    """Post-process narrative text in ``lang``: substitute English prose lab
    names with their ``lang`` names (アルブミン for "Albumin" in Japanese).
    Deterministic; abbreviations and text without a table entry are kept
    verbatim, and a language without differing names leaves the text
    unchanged. Only the matched lab-name token is replaced.
    """
    pattern = _get_lab_name_pattern(lang)
    if not text or pattern is None:
        return text
    terms = _lab_prose_terms(lang)

    def _repl(m: re.Match) -> str:
        return terms[m.group(1).lower()]

    return pattern.sub(_repl, text)


def localize_lab_names_in_sections(sections: dict[str, str], lang: str) -> dict[str, str]:
    """Apply the text-level lab-name post-processor to every section
    value. Returns a NEW dict; leaves the input untouched so caller
    replacement is explicit at the call site.
    """
    return {k: localize_lab_names_in_text(v, lang) for k, v in sections.items()}
