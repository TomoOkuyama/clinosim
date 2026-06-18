"""Output-format adapter registry (AD-58).

CIF is the only simulation output (AD-17). Format adapters read the CIF directory and
emit a concrete export format. New formats (SS-MIX, FHIR R3, ...) register one adapter
here instead of editing CLI dispatch. Adapters depend only on CIF + clinosim.codes +
clinosim.locale (AD-17 / AD-25).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class OutputContext:
    """Shared, format-agnostic context passed to every adapter."""

    country: str = "US"
    # optional narrative dir folded into output (e.g. FHIR DocumentReference)
    narrative_version: str = ""
    # format-specific extras (forward-compatible)
    options: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class OutputAdapter(Protocol):
    """A CIF-consuming export adapter. Implementations are plain classes (duck-typed)."""

    format_id: str  # registry key + CLI value, e.g. "fhir-r4"
    description: str  # shown in CLI help / available_formats()
    subdir: str  # output subdirectory name, e.g. "fhir_r4"

    def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None: ...


_ADAPTERS: dict[str, OutputAdapter] = {}
_builtins_loaded = False


def register_output_adapter(adapter: OutputAdapter) -> None:
    """Register (or replace) an adapter by its format_id. Idempotent."""
    _ADAPTERS[adapter.format_id] = adapter


def _ensure_builtins() -> None:
    """Import the built-in adapters module once so it self-registers."""
    global _builtins_loaded
    if not _builtins_loaded:
        _builtins_loaded = True
        import clinosim.modules.output.adapters_builtin  # noqa: F401  (registers on import)


def get_adapter(format_id: str) -> OutputAdapter:
    """Return the adapter for format_id, or raise KeyError with the available list."""
    _ensure_builtins()
    if format_id not in _ADAPTERS:
        raise KeyError(
            f"Unknown output format {format_id!r}. "
            f"Available: {', '.join(sorted(_ADAPTERS))}"
        )
    return _ADAPTERS[format_id]


def available_formats() -> list[tuple[str, str]]:
    """Return [(format_id, description), ...] sorted by format_id."""
    _ensure_builtins()
    return sorted((a.format_id, a.description) for a in _ADAPTERS.values())
