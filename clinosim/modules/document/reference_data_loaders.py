"""Document module reference data loaders (Tier 1 #3 α-min-1 PR1 Task 5).

Provides loaders for disease-agnostic baseline + per-disease override
reference data used by TemplateNarrativeGenerator (Task 6) and the
document enricher (Task 8).

Pattern follows clinosim/modules/allergy/engine.py (Task 2 precedent)
and clinosim/modules/document/narrative/registry.py (Task 3 precedent):
- @lru_cache(maxsize=1) loader singletons
- 6-layer silent-no-op defense validators:
    Layer 1: empty top-level guard
    Layer 2: missing required top-level key guard
    Layer 3: per-bucket empty/null guard
    Layer 4: required-key coverage (baseline keys + per-entry field coverage)
    Layer 5: validators run BEFORE data is returned (pre-use ordering)
    Layer 6: per-entry required-field check (fail-loud on missing)

File ownership:
  Task 5 (this file): loaders + validators
  Task 8: enricher engine (imports from this file)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

# Required top-level keys for baseline and the minimum archetype.
_PHYSICAL_EXAM_REQUIRED_BASELINE_ARCHETYPE = "uncomplicated_improvement"
_PHYSICAL_EXAM_REQUIRED_BASELINE_DAY = "day_0"
_PHYSICAL_EXAM_BODY_SYSTEMS = frozenset({"general", "cardiovascular", "respiratory", "abdominal", "neurological"})

# Required keys in baseline for discharge instructions.
_DISCHARGE_BASELINE_REQUIRED_KEYS = ("hydrate", "rest", "follow_up")


# ─────────────────────────────────────────────────────────────────
# physical_exam_findings.yaml
# ─────────────────────────────────────────────────────────────────


def _validate_physical_exam_findings(data: dict[str, Any]) -> None:
    """Fail-loud 6-layer validation of physical_exam_findings.yaml.

    Layer 1: empty top-level guard
    Layer 2: missing 'baseline' key guard
    Layer 3: baseline.uncomplicated_improvement existence guard
    Layer 4: baseline.uncomplicated_improvement.day_0 existence guard
    Layer 5: day_0 has at least one recognised body-system key
    Layer 6: 'findings' top-level key presence (per-disease override section)
    """
    if not data:
        raise ValueError("physical_exam_findings.yaml: empty top-level")

    if "baseline" not in data:
        raise ValueError("physical_exam_findings.yaml: missing 'baseline' key")

    baseline = data["baseline"]
    if not baseline or not isinstance(baseline, dict):
        raise ValueError("physical_exam_findings.yaml: 'baseline' is empty or not a mapping")

    # Layer 3 — required archetype must be present
    if _PHYSICAL_EXAM_REQUIRED_BASELINE_ARCHETYPE not in baseline:
        raise ValueError(
            f"physical_exam_findings.yaml: baseline missing required archetype "
            f"'{_PHYSICAL_EXAM_REQUIRED_BASELINE_ARCHETYPE}'"
        )

    archetype = baseline[_PHYSICAL_EXAM_REQUIRED_BASELINE_ARCHETYPE]
    if not archetype or not isinstance(archetype, dict):
        raise ValueError(
            f"physical_exam_findings.yaml: baseline.{_PHYSICAL_EXAM_REQUIRED_BASELINE_ARCHETYPE} "
            f"is empty or not a mapping"
        )

    # Layer 4 — required day key
    if _PHYSICAL_EXAM_REQUIRED_BASELINE_DAY not in archetype:
        raise ValueError(
            f"physical_exam_findings.yaml: "
            f"baseline.{_PHYSICAL_EXAM_REQUIRED_BASELINE_ARCHETYPE} missing "
            f"'{_PHYSICAL_EXAM_REQUIRED_BASELINE_DAY}'"
        )

    day_0 = archetype[_PHYSICAL_EXAM_REQUIRED_BASELINE_DAY]
    if not day_0 or not isinstance(day_0, dict):
        raise ValueError(
            f"physical_exam_findings.yaml: "
            f"baseline.{_PHYSICAL_EXAM_REQUIRED_BASELINE_ARCHETYPE}"
            f".{_PHYSICAL_EXAM_REQUIRED_BASELINE_DAY} is empty or not a mapping"
        )

    # Layer 5 — at least one body-system key present
    if not any(s in day_0 for s in _PHYSICAL_EXAM_BODY_SYSTEMS):
        raise ValueError(
            f"physical_exam_findings.yaml: "
            f"baseline.{_PHYSICAL_EXAM_REQUIRED_BASELINE_ARCHETYPE}"
            f".{_PHYSICAL_EXAM_REQUIRED_BASELINE_DAY} has no recognised body-system key "
            f"(expected one of: {sorted(_PHYSICAL_EXAM_BODY_SYSTEMS)})"
        )

    # Layer 6 — per-disease override section must be present (may be empty dict)
    if "findings" not in data:
        raise ValueError("physical_exam_findings.yaml: missing 'findings' key")


@lru_cache(maxsize=1)
def load_physical_exam_findings() -> dict[str, Any]:
    """Load physical_exam_findings.yaml + validate. Cached singleton.

    Returns the full top-level dict (with 'baseline' and 'findings' keys).
    Task 6 TemplateNarrativeGenerator uses the 'baseline' section as
    fallback and the 'findings' section for per-disease overrides.
    """
    with (_REF_DIR / "physical_exam_findings.yaml").open() as f:
        data: dict[str, Any] = yaml.safe_load(f)
    _validate_physical_exam_findings(data)
    return data


# ─────────────────────────────────────────────────────────────────
# discharge_instructions.yaml
# ─────────────────────────────────────────────────────────────────


def _validate_discharge_instructions(data: dict[str, Any]) -> None:
    """Fail-loud 6-layer validation of discharge_instructions.yaml.

    Layer 1: empty top-level guard
    Layer 2: missing 'baseline' key guard
    Layer 3: baseline is non-empty mapping guard
    Layer 4: required baseline keys (hydrate / rest / follow_up) presence
    Layer 5: each baseline entry has both 'en' and 'ja' keys
    Layer 6: 'disease_specific' top-level key presence (may be empty)
    """
    if not data:
        raise ValueError("discharge_instructions.yaml: empty top-level")

    if "baseline" not in data:
        raise ValueError("discharge_instructions.yaml: missing 'baseline' key")

    baseline = data["baseline"]
    if not baseline or not isinstance(baseline, dict):
        raise ValueError("discharge_instructions.yaml: 'baseline' is empty or not a mapping")

    # Layer 4 — required keys
    for req_key in _DISCHARGE_BASELINE_REQUIRED_KEYS:
        if req_key not in baseline:
            raise ValueError(f"discharge_instructions.yaml: baseline missing required key '{req_key}'")

    # Layer 5 — each entry must have 'en' and 'ja'
    for key, entry in baseline.items():
        if not entry or not isinstance(entry, dict):
            raise ValueError(f"discharge_instructions.yaml: baseline[{key!r}] is empty or not a mapping")
        if "en" not in entry:
            raise ValueError(f"discharge_instructions.yaml: baseline[{key!r}] missing 'en'")
        if "ja" not in entry:
            raise ValueError(f"discharge_instructions.yaml: baseline[{key!r}] missing 'ja'")

    # Layer 6 — disease_specific section must be present
    if "disease_specific" not in data:
        raise ValueError("discharge_instructions.yaml: missing 'disease_specific' key")

    # Validate each disease_specific entry if present
    disease_specific = data.get("disease_specific") or {}
    if disease_specific and isinstance(disease_specific, dict):
        for disease_id, overrides in disease_specific.items():
            if overrides is None:
                continue  # empty disease entry is allowed (no-op)
            if not isinstance(overrides, dict):
                raise ValueError(
                    f"discharge_instructions.yaml: disease_specific[{disease_id!r}] must be a mapping or null"
                )
            for key, entry in overrides.items():
                if not entry or not isinstance(entry, dict):
                    raise ValueError(
                        f"discharge_instructions.yaml: "
                        f"disease_specific[{disease_id!r}][{key!r}] "
                        f"is empty or not a mapping"
                    )
                if "en" not in entry:
                    raise ValueError(
                        f"discharge_instructions.yaml: disease_specific[{disease_id!r}][{key!r}] missing 'en'"
                    )
                if "ja" not in entry:
                    raise ValueError(
                        f"discharge_instructions.yaml: disease_specific[{disease_id!r}][{key!r}] missing 'ja'"
                    )


@lru_cache(maxsize=1)
def load_discharge_instructions() -> dict[str, Any]:
    """Load discharge_instructions.yaml + validate. Cached singleton.

    Returns the full top-level dict (with 'baseline' and 'disease_specific' keys).
    Task 6 TemplateNarrativeGenerator merges baseline + disease_specific entries,
    with disease_specific taking precedence for shared keys.
    """
    with (_REF_DIR / "discharge_instructions.yaml").open() as f:
        data: dict[str, Any] = yaml.safe_load(f)
    _validate_discharge_instructions(data)
    return data
