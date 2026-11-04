"""Panel detection for lab Order grouping (PR1 ServiceRequest foundation).

Reads ``lab_panels.yaml`` (moved from ``output/reference_data/`` in this task
to unify panel data ownership; "panel" is fundamentally an ordering concept) and
classifies a list of lab specs into panel groups and stand-alone tests.

Priority order is critical for HCO3 dual-membership (ABG ∧ BMP) — HCO3 is
assigned to ABG first (priority winner), then ABG's min_components is checked.
If ABG falls below min_components, HCO3 stays orphaned in ABG bucket and the
whole ABG group becomes stand-alone (conservative; no BMP fallback).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from clinosim.codes import code_exists
from clinosim.datafiles import load_data_yaml
from clinosim.locale.localized import language_slot

_HERE = Path(__file__).resolve().parent
# The one panel definition, shared with result generation (Issue #2332).
_PANEL_YAML = _HERE.parent / "observation" / "reference_data" / "lab_panels.yaml"

PANEL_PRIORITY_ORDER: tuple[str, ...] = ("ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA", "Checkup")
"""Priority order for panel matching (header of lab_panels.yaml).

Verified against the YAML header comment at import time via
``_validate_panel_definitions`` (forward + reverse coverage against YAML keys).
"""


def _validate_panel_definitions(panels: dict[str, dict[str, Any]]) -> None:
    """Validate panel YAML schema + canonical-constant cross-reference.

    Implements the per-validator 6-layer defense pattern (CLAUDE.md):
    (1) empty top-level rejected
    (2) per-bucket empty guards
    (3) unknown YAML keys rejected (YAML panels not in PANEL_PRIORITY_ORDER)
    (4) PANEL_PRIORITY_ORDER forward-coverage (every constant has YAML entry)
    (5) range/type checks (min_components positive int, components non-empty list)
    (6) authoritative cross-validation: LOINC code resolves via ``code_exists(..., exact=True)``
        + YAML key order matches PANEL_PRIORITY_ORDER (iteration-order is
        load-bearing for ``group_lab_orders`` priority grouping)

    Raises:
        ValueError: on any validation failure.
    """
    # Layer 1: empty top-level
    if not panels:
        raise ValueError("lab_panels.yaml panels section is empty")

    yaml_keys = set(panels.keys())
    expected = set(PANEL_PRIORITY_ORDER)

    # Layer 4: forward-coverage — every PANEL_PRIORITY_ORDER entry must be in YAML
    missing_in_yaml = expected - yaml_keys
    if missing_in_yaml:
        raise ValueError(f"lab_panels.yaml missing panels declared in PANEL_PRIORITY_ORDER: {sorted(missing_in_yaml)}")

    # Layer 3: unknown keys — YAML panels not in PANEL_PRIORITY_ORDER (silent-no-op risk)
    extra_in_yaml = yaml_keys - expected
    if extra_in_yaml:
        raise ValueError(
            f"lab_panels.yaml has panels NOT in PANEL_PRIORITY_ORDER (silent-no-op risk): {sorted(extra_in_yaml)}"
        )

    # Layer 6 (key-order): YAML insertion order must match PANEL_PRIORITY_ORDER.
    # group_lab_orders iterates panels.items() — a hand-reorder of the YAML would
    # silently break priority grouping (e.g. BMP would steal HCO3 from ABG).
    yaml_order = tuple(panels.keys())
    if yaml_order != PANEL_PRIORITY_ORDER:
        raise ValueError(
            f"lab_panels.yaml key order {yaml_order} does not match "
            f"PANEL_PRIORITY_ORDER {PANEL_PRIORITY_ORDER}. "
            f"Iteration-order is load-bearing for grouping priority."
        )

    for name, panel in panels.items():
        # Layer 2: per-bucket empty guard + required-field presence
        for field in ("loinc", "components", "min_components", "display"):
            if field not in panel:
                raise ValueError(f"Panel '{name}' missing required field '{field}'")
        if not language_slot(panel["display"], "en"):
            raise ValueError(f"Panel '{name}' has empty display string")

        # Layer 5: type/range checks
        if not isinstance(panel["components"], list) or not panel["components"]:
            raise ValueError(f"Panel '{name}' has empty or non-list components")
        if not isinstance(panel["min_components"], int) or panel["min_components"] < 1:
            raise ValueError(f"Panel '{name}' min_components must be positive int")

        # Layer 6a (LOINC): authoritative cross-validation — code must resolve in
        # codes/data/loinc.yaml. PR-90 lesson: a typo'd LOINC passes required-field
        # check (Layer 2) but should fail at import time, not only at test-time.
        if not code_exists("loinc", panel["loinc"], exact=True):
            raise ValueError(
                f"Panel '{name}' has unknown LOINC code '{panel['loinc']}' (not in clinosim/codes/data/loinc.yaml)"
            )


@lru_cache(maxsize=1)
def load_panel_definitions() -> dict[str, dict[str, Any]]:
    """Return panel definitions from lab_panels.yaml (cached, validated).

    Key order matches the YAML insertion order, which is the grouping priority
    (ABG > CBC > BMP > LFT > Lipid > Coag > UA) — this order is load-bearing
    for ``classify_lab_specs`` and for ``group_lab_orders`` in
    ``_fhir_diagnostic_report.py`` (both iterate panels.items()).

    Returns:
        Validated dict mapping panel name → panel definition dict.

    Raises:
        ValueError: if YAML fails schema/coverage validation.
        FileNotFoundError: if lab_panels.yaml is missing.
    """
    data = load_data_yaml(_PANEL_YAML)
    panels: dict[str, dict[str, Any]] = (data or {}).get("panels") or {}
    _validate_panel_definitions(panels)
    return panels


def classify_lab_specs(
    lab_specs: list[dict[str, Any]],
    panels: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Classify lab specs into panel groups + stand-alone tests.

    2-pass deterministic algorithm:

    - Pass A: For each lab_spec, try each panel in PANEL_PRIORITY_ORDER;
      first match wins (handles HCO3 dual-membership: ABG > BMP).
    - Pass B: For each panel, check len(matches) >= min_components.
      If yes, panel is accepted; else its matches become stand-alone.
      No cross-panel fallback (conservative rule — avoids double-assignment).

    Args:
        lab_specs: List of test specs (dicts with a ``"test"`` key naming the analyte).
        panels: Panel definitions from ``load_panel_definitions()``.

    Returns:
        Tuple of:
        - ``panel_groups``: ``{panel_name: [lab_spec, ...]}`` — accepted panels
          in PANEL_PRIORITY_ORDER insertion order.
        - ``stand_alones``: list of lab_specs not assigned to any accepted panel,
          in original input order.
    """
    # Pass A: priority-first matching — iterate specs, assign to first matching panel
    panel_match_candidates: dict[str, list[dict[str, Any]]] = {}
    for lab_spec in lab_specs:
        test_name = lab_spec.get("test", "")
        for panel_name in PANEL_PRIORITY_ORDER:
            if panel_name not in panels:
                continue
            if test_name in panels[panel_name]["components"]:
                panel_match_candidates.setdefault(panel_name, []).append(lab_spec)
                break  # priority-first: stop at first matching panel

    # Pass B: min_components gate — reject panels below threshold
    panel_groups: dict[str, list[dict[str, Any]]] = {}
    accepted_ids: set[int] = set()
    for panel_name, matches in panel_match_candidates.items():
        min_required = panels[panel_name]["min_components"]
        if len(matches) >= min_required:
            panel_groups[panel_name] = matches
            accepted_ids.update(id(s) for s in matches)
    # Specs not in any accepted panel (unmatched + rejected-panel members) → stand-alone
    stand_alones = [s for s in lab_specs if id(s) not in accepted_ids]
    return panel_groups, stand_alones
