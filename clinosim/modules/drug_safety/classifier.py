"""Drug-name → class[] resolver, alias-aware.

Case-insensitive substring match against canonical names + aliases,
matching the pattern used by ``clinosim.modules.monitoring.enricher`` and
``physiology.engine._WARFARIN_NAMES``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_HERE = Path(__file__).resolve().parent
_DRUG_CLASSES_YAML = _HERE / "reference_data" / "drug_classes.yaml"


@lru_cache(maxsize=1)
def _load_mappings() -> dict[str, dict[str, Any]]:
    with _DRUG_CLASSES_YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("mappings", {})


@lru_cache(maxsize=1)
def _build_alias_index() -> list[tuple[str, str]]:
    """Return [(lowercased-alias-or-canonical, canonical), ...] sorted by length desc.

    Length-desc ordering ensures that longer keys (e.g. "sertraline") match
    before shorter substrings ("acei" inside "aceinhibitor" would falsely match
    otherwise). Exact matches are handled first via the dict below.
    """
    pairs: list[tuple[str, str]] = []
    for canonical, entry in _load_mappings().items():
        pairs.append((canonical.strip().lower(), canonical))
        for alias in entry.get("aliases", []) or []:
            pairs.append((str(alias).strip().lower(), canonical))
    # longest key first to prefer specific match
    pairs.sort(key=lambda kv: -len(kv[0]))
    return pairs


@lru_cache(maxsize=1)
def _exact_alias_map() -> dict[str, str]:
    return {k: v for k, v in _build_alias_index()}


def canonical_name(drug_name: str) -> str | None:
    """Resolve any alias / case / whitespace variant to the canonical name."""
    if not drug_name:
        return None
    key = drug_name.strip().lower()
    exact = _exact_alias_map()
    if key in exact:
        return exact[key]
    # substring fallback — matches "warfarin 3mg PO" → Warfarin
    for alias_key, canonical in _build_alias_index():
        if alias_key and alias_key in key:
            return canonical
    return None


def resolve_classes(drug_name: str) -> list[str]:
    """Return the ordered class list for the resolved drug, or [] if unknown."""
    canonical = canonical_name(drug_name)
    if canonical is None:
        return []
    entry = _load_mappings().get(canonical, {})
    return list(entry.get("classes", []))


def japanese_display(drug_name: str) -> str | None:
    canonical = canonical_name(drug_name)
    if canonical is None:
        return None
    entry = _load_mappings().get(canonical, {})
    return entry.get("drug_ja")
