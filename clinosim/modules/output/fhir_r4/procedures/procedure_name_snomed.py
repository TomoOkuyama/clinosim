"""Order-derived Procedure display-name → SNOMED CT lookup (Issue #1282 Sub-B).

The Order → Procedure emit path in
``modules/output/fhir_r4/lib/inline_bb.py`` previously emitted
`Procedure.code` with only `text` populated (empty `coding` array). At
p=10k s=354 that was 36 % of all Procedure resources (Issue #1282),
so downstream analytics filtering by `Procedure.code.coding[*].code`
missed the underlying clinical event.

This module loads the `procedure_name_snomed.yaml` crosswalk once and
exposes ``resolve_procedure_snomed(display_name)`` — first-match-wins
substring match against the trimmed lowercase display name. Callers
attach the returned ``(snomed_code, display_en)`` tuple to
`Procedure.code.coding[0]` when a match is found, otherwise fall
back to the pre-existing text-only shape.

Determinism: pure function of the input string + the yaml. No RNG.

Verification: every SNOMED code in the yaml is verified against
``tx.fhir.org`` `$lookup` under `http://snomed.info/sct` (see the
yaml file's header comment).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_YAML_PATH = _HERE / "procedure_name_snomed.yaml"


@lru_cache(maxsize=1)
def _load_entries() -> list[tuple[str, str, str]]:
    """Return the crosswalk as a list of ``(match, snomed, display_en)``
    tuples in the declared order. First-match-wins at lookup time.

    Never raises. A malformed yaml results in an empty crosswalk (the
    caller falls back to text-only emit — same as pre-#1282 behaviour)."""
    try:
        with _YAML_PATH.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return []
    entries = data.get("entries") or []
    out: list[tuple[str, str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        m = str(entry.get("match") or "").strip().lower()
        snomed = str(entry.get("snomed") or "").strip()
        display = str(entry.get("display_en") or "").strip()
        if not m or not snomed:
            continue
        out.append((m, snomed, display))
    return out


def resolve_procedure_snomed(display_name: str) -> tuple[str, str] | None:
    """First-match-wins substring lookup against the crosswalk.

    Returns ``(snomed_code, display_en)`` on hit, ``None`` on miss.
    Empty / non-string input returns ``None``.
    """
    if not display_name:
        return None
    if not isinstance(display_name, str):
        return None
    needle = display_name.strip().lower()
    if not needle:
        return None
    for match, snomed, display in _load_entries():
        if match in needle:
            return snomed, display
    return None
