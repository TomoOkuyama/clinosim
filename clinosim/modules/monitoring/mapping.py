"""YAML loader for the chronic-medication → monitoring-lab mapping (Issue #757).

Loads `reference_data/medication_monitoring.yaml` into a lookup structure
consumed by `enrich_medication_monitoring`. The loader is intentionally
minimal:

- No caching decorator — the enricher is called once per POST_RECORDS pass
  per run, and the file is small (<10 KB expected for the full pair set).
- Parses into plain dicts (not Pydantic / dataclass) to keep the module's
  external surface small and match the sibling `sdoh.load_social_history`
  loader style.
- Validates schema at load time (fail-loud on missing required keys) so
  a typo in the YAML surfaces immediately rather than as a silent "drug
  never matched" downstream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_YAML_PATH = Path(__file__).parent / "reference_data" / "medication_monitoring.yaml"


def load_medication_monitoring(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the drug → monitoring-labs mapping.

    Returns a dict keyed by canonical drug name (as declared in YAML) whose
    value is `{"aliases": [...], "monitoring": [{lab, loinc, rationale}, ...]}`.
    Tests can override the file path via the optional `path` argument.

    Raises `ValueError` on schema violations (missing `mappings`, missing
    per-drug `monitoring` list, missing per-lab `lab`/`loinc` keys). No
    silent failure — invalid YAML fails loud at load time rather than
    producing a mysterious "no drugs matched" runtime signature.
    """
    p = path or _YAML_PATH
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    mappings = raw.get("mappings")
    if not isinstance(mappings, dict):
        raise ValueError(f"medication_monitoring.yaml at {p}: missing or non-dict top-level 'mappings' key")
    for drug, entry in mappings.items():
        if not isinstance(entry, dict):
            raise ValueError(f"medication_monitoring.yaml: drug '{drug}' entry must be a dict")
        aliases = entry.get("aliases") or []
        if not isinstance(aliases, list):
            raise ValueError(f"medication_monitoring.yaml: drug '{drug}' aliases must be a list")
        monitoring = entry.get("monitoring")
        if not isinstance(monitoring, list) or not monitoring:
            raise ValueError(f"medication_monitoring.yaml: drug '{drug}' must declare a non-empty 'monitoring' list")
        for i, m in enumerate(monitoring):
            if not isinstance(m, dict):
                raise ValueError(f"medication_monitoring.yaml: drug '{drug}' monitoring[{i}] must be a dict")
            if not m.get("lab"):
                raise ValueError(f"medication_monitoring.yaml: drug '{drug}' monitoring[{i}] missing required 'lab'")
            if not m.get("loinc"):
                raise ValueError(f"medication_monitoring.yaml: drug '{drug}' monitoring[{i}] missing required 'loinc'")
    return mappings


def match_drugs(current_medications: list, mapping: dict[str, Any]) -> list[str]:
    """Return the list of canonical drug names the patient is on.

    Case-insensitive substring match across the drug's canonical name and
    every alias. Matches the pattern used by `physiology.engine.medication_flags_from_context`
    (`_WARFARIN_NAMES`) so "Warfarin 3mg PO", "ワルファリン 3mg", and
    "Coumadin 5mg" all resolve to the same "Warfarin" mapping entry.

    `current_medications` accepts either `HomeMedication` dataclass entries
    (with `.drug_name` attribute) or plain strings (defensive fallback for
    tests / legacy call sites); other shapes are silently skipped.
    """
    matched: list[str] = []
    for drug, entry in mapping.items():
        needles = [drug.lower(), *(str(a).lower() for a in (entry.get("aliases") or []))]
        for med in current_medications or []:
            haystack = getattr(med, "drug_name", None) or (med if isinstance(med, str) else "")
            haystack = str(haystack).lower()
            if any(needle and needle in haystack for needle in needles):
                matched.append(drug)
                break
    return matched
