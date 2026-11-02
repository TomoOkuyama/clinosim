"""LocalizedTable — the base class of display and translation tables
(code-mapping spec §2.3, Issue #2471).

A table is one section of a ``locale/shared`` YAML: ``{key: {lang: text}}``.
The base class owns the operations every table shares — finding a key's
entry, choosing its language (requested, then English) and falling back.
They are ``@final``: a subclass changes only the hook ``candidates`` (how a
key is matched) and the declared ``humanize_unknown`` property.

Tables read their entries through the existing cached loaders
(``load_vocabulary``, ``load_narrative_imaging``, ...), so the loaders stay the
single place a file is parsed and the public entry points
(``vocab_display``, ``imaging_exam_display``, ``prompt_label``,
``narrative_label``) delegate here. ``localized_tables()`` lists every table so
tests can iterate them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, final

from clinosim.locale.localized import localized

__all__ = ["ImagingExamTable", "LocalizedTable", "localized_table", "localized_tables"]


@dataclass(frozen=True)
class LocalizedTable:
    """One display table (``kind="display-table"``, keyed by internal slug,
    ``en`` required) or translation table (``kind="translation-table"``,
    keyed by the English source text)."""

    name: str  # "<file stem>.<section>"
    source: Callable[[], Mapping[str, Any] | None]  # the section's entries
    kind: str = "display-table"
    # Whether an unknown key is humanised (underscores → spaces) instead of
    # returning the caller's fallback; only for tables whose slug coverage is
    # tested (spec §6.4).
    humanize_unknown: bool = False

    FINAL_OPERATIONS: ClassVar[tuple[str, ...]] = ("entries", "get")

    def candidates(self, key: str) -> tuple[str, ...]:
        """Hook: the keys tried for ``key``, in order (exact, then lower-cased)."""
        raw = str(key)
        return (raw, raw.strip().lower())

    @final
    def entries(self) -> Mapping[str, Any]:
        return self.source() or {}

    @final
    def get(self, key: str, lang: str, *, fallback: str = "") -> str:
        """``key`` in ``lang`` (then English) from the first candidate that has
        text; else the humanised key (``humanize_unknown``) or ``fallback``."""
        entries = self.entries()
        for candidate in self.candidates(key):
            entry = entries.get(candidate)
            if isinstance(entry, Mapping):
                text = localized(entry, lang)
                if text:
                    return text
        if self.humanize_unknown and key:
            return str(key).replace("_", " ")
        return fallback


@dataclass(frozen=True)
class ImagingExamTable(LocalizedTable):
    """Imaging exams match case-insensitively after collapsing whitespace, in
    both the spaced and the underscore form (Issue #2268)."""

    def candidates(self, key: str) -> tuple[str, ...]:
        norm = " ".join(str(key or "").strip().lower().split())
        return (norm, norm.replace(" ", "_"), norm.replace("_", " ")) if norm else ()


def _section(loader: Callable[[], Mapping[str, Any]], section: str) -> Callable[[], Mapping[str, Any] | None]:
    def source() -> Mapping[str, Any] | None:
        value = loader().get(section)
        return value if isinstance(value, Mapping) else None

    return source


def _bundle_tables(
    stem: str, loader: Callable[[], Mapping[str, Any]], kind: str = "display-table"
) -> list[LocalizedTable]:
    return [LocalizedTable(f"{stem}.{section}", _section(loader, section), kind) for section in loader()]


def localized_tables() -> dict[str, LocalizedTable]:
    """Every display and translation table, by name."""
    from clinosim.locale.loaders import narrative as n

    tables: list[LocalizedTable] = [
        ImagingExamTable("narrative_imaging.imaging", n.load_narrative_imaging, humanize_unknown=True),
        LocalizedTable("lab_display.lab_names", n.load_lab_display),
        LocalizedTable("narrative_lab_flags.lab_flags", n.load_narrative_lab_flags),
        LocalizedTable("narrative_stage_tokens.stage_tokens", n.load_narrative_stage_tokens),
        LocalizedTable("narrative_op_approach.op_approach", n.load_narrative_op_approach, "translation-table"),
        LocalizedTable("narrative_op_implants.op_implants", n.load_narrative_op_implants, "translation-table"),
        LocalizedTable("narrative_archetypes.archetypes", n.load_narrative_archetypes),
        LocalizedTable("narrative_complications.complications", n.load_narrative_complications),
    ]
    tables += _bundle_tables("vocabulary", n.load_vocabulary)
    tables += _bundle_tables("narrative_labels", n.load_narrative_labels)
    tables += _bundle_tables("llm_prompt_labels", n.load_llm_prompt_labels)
    return {t.name: t for t in tables}


def localized_table(name: str) -> LocalizedTable:
    """The table ``name`` (``"<file stem>.<section>"``); ``KeyError`` when unknown."""
    return localized_tables()[name]
