"""Locale shared I/O primitives (hardcoded-review Phase B1).

Private module factored out of ``clinosim/locale/loader.py`` so submodules
under ``clinosim/locale/loaders/`` can share the yaml-reading primitives
without re-importing from ``loader.py`` (which would create a cycle: the
loader module re-exports from the submodules, so the submodules can't
import ``loader`` back).

Public API: nothing. The names start with ``_`` and are only consumed by
sibling locale modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_LOCALE_DIR = Path(__file__).parent

# ISO 3166-1 alpha-2 lowercase.
_COUNTRY_DIR_MAP = {"JP": "jp", "US": "us"}


def _country_dir(country: str) -> Path:
    """Return the per-country locale directory path.

    See the original ``loader.py`` docstring: unknown countries fall
    through to a lowercased folder name; P2-14 forbids any resolution
    that would land in a leading-underscore scaffold directory.
    """
    dir_name = _COUNTRY_DIR_MAP.get(country, country.lower())
    if dir_name.startswith("_"):
        raise ValueError(
            f"country={country!r} resolves to reserved scaffold folder "
            f"{dir_name!r}. Country codes must map to a real locale."
        )
    return _LOCALE_DIR / dir_name


def _load_yaml(path: Path, fallback: Any = None) -> Any:
    """Load a yaml file; return ``fallback`` (default ``{}``) when absent."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or fallback
    return fallback if fallback is not None else {}


# Cross-locale fallback defaults — authoritative yaml at
# ``clinosim/locale/shared/fallback_defaults.yaml`` (hardcoded-review
# Phase A14). The yaml carries all four fallback blocks (names /
# formatting / demographics / encounter_disposition); the Python
# constants below preserve the historical module-level symbols so every
# call site stays unchanged. They live in ``_io.py`` so that submodules
# under ``clinosim/locale/loaders/`` can import them without a cycle
# back through ``loader.py`` (hardcoded-review Phase C2c).
_FALLBACK_DEFAULTS_PATH = _LOCALE_DIR / "shared" / "fallback_defaults.yaml"


def _read_fallback_defaults() -> dict[str, Any]:
    if not _FALLBACK_DEFAULTS_PATH.exists():
        return {}
    with open(_FALLBACK_DEFAULTS_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw if isinstance(raw, dict) else {}


_FALLBACK_DEFAULTS: dict[str, Any] = _read_fallback_defaults()

_FALLBACK_NAMES: dict[str, Any] = _FALLBACK_DEFAULTS.get("names", {}) or {}
_FALLBACK_FORMATTING: dict[str, Any] = _FALLBACK_DEFAULTS.get("formatting", {}) or {}
_FALLBACK_DEMOGRAPHICS: dict[str, Any] = _FALLBACK_DEFAULTS.get("demographics", {}) or {}
_FALLBACK_ENCOUNTER_DISPOSITION: dict[str, Any] = _FALLBACK_DEFAULTS.get("encounter_disposition", {}) or {}
