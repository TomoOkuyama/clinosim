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

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from clinosim.codes import code_exists
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.localized import language_slot

_HERE = Path(__file__).resolve().parent
# The one panel definition, shared with result generation (Issue #2332).
_PANEL_YAML = _HERE.parent / "observation" / "reference_data" / "lab_panels.yaml"

PANEL_PRIORITY_ORDER: tuple[str, ...] = ("ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA", "Checkup")
"""Priority order for panel matching (header of lab_panels.yaml).

Verified against the YAML header comment at import time via
the ``LabPanels`` model (forward + reverse coverage and order against YAML keys).
"""


class _Panel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loinc: str
    display: Any
    components: list[Any] = Field(min_length=1)
    min_components: StrictInt = Field(ge=1)
    # Component-name -> LOINC override inside this panel (coding_strategy).
    component_loinc: dict[str, str] = Field(default_factory=dict)
    # Drop the panel report when none of its components were resulted (diagnostic_report).
    skip_if_no_components_present: bool = False

    @field_validator("loinc")
    @classmethod
    def _registered(cls, code: str) -> str:
        """PR-90 lesson: a typo'd LOINC passes the required-field check, so it
        must resolve in codes/data/loinc.yaml at load time."""
        if not code_exists("loinc", code, exact=True):
            raise ValueError(f"unknown LOINC code {code!r} (not in clinosim/codes/data/loinc.yaml)")
        return code

    @field_validator("display")
    @classmethod
    def _has_an_english_display(cls, display: Any) -> Any:
        if not language_slot(display, "en"):
            raise ValueError("empty display string")
        return display


class LabPanels(BaseModel):
    """Shape of lab_panels.yaml: exactly the PANEL_PRIORITY_ORDER panels, in
    that order, each with a registered LOINC code, an English display, a
    non-empty component list and a positive ``min_components``."""

    model_config = ConfigDict(extra="forbid")

    panels: dict[str, _Panel]

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        if not (data or {}).get("panels"):
            raise ValueError("lab_panels.yaml panels section is empty")
        return data

    @field_validator("panels")
    @classmethod
    def _priority_order(cls, panels: dict[str, _Panel]) -> dict[str, _Panel]:
        keys, expected = set(panels), set(PANEL_PRIORITY_ORDER)
        if expected - keys:
            raise ValueError(
                f"lab_panels.yaml missing panels declared in PANEL_PRIORITY_ORDER: {sorted(expected - keys)}"
            )
        if keys - expected:
            raise ValueError(
                f"lab_panels.yaml has panels NOT in PANEL_PRIORITY_ORDER (silent-no-op risk): {sorted(keys - expected)}"
            )
        # group_lab_orders iterates panels.items() — a hand-reorder of the YAML
        # would silently break priority grouping (BMP would steal HCO3 from ABG).
        if tuple(panels) != PANEL_PRIORITY_ORDER:
            raise ValueError(
                f"lab_panels.yaml key order {tuple(panels)} does not match "
                f"PANEL_PRIORITY_ORDER {PANEL_PRIORITY_ORDER}. "
                f"Iteration-order is load-bearing for grouping priority."
            )
        return panels


@lru_cache(maxsize=1)
def load_panel_definitions() -> dict[str, dict[str, Any]]:
    """Return panel definitions from lab_panels.yaml (cached, validated).

    Key order matches the YAML insertion order, which is the grouping priority
    (ABG > CBC > BMP > LFT > Lipid > Coag > UA) — this order is load-bearing
    for ``classify_lab_specs`` and for ``group_lab_orders`` in
    ``fhir_r4/labs/diagnostic_report.py`` (both iterate panels.items()).

    Returns:
        Validated dict mapping panel name → panel definition dict.

    Raises:
        ValueError: if YAML fails schema/coverage validation.
        FileNotFoundError: if lab_panels.yaml is missing.
    """
    panels: dict[str, dict[str, Any]] = load_validated_yaml(_PANEL_YAML, LabPanels)["panels"]
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
