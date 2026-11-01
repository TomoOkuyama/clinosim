"""UCUM units for FHIR Quantities (Issue #2265).

:func:`ucum_code` maps a clinical unit spelling to its UCUM code and
:func:`ucum_quantity` builds a FHIR ``Quantity``; emitters use these for every
Quantity instead of assembling the ``system`` / ``code`` pair by hand.
:func:`ucum_prose` is the unit as written in prose (``mm[Hg]`` → ``mmHg``).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.codes.loader import get_system_uri


# Human-readable → UCUM canonical token map (issue #204, 2026-07-17).
#
# fhir-jp-validator 2026-07-17 §【最優先 1】surfaced 6,203 errors on
# MedicationAdministration Quantity.code — UCUM does not accept the informal
# clinical spellings that appear in disease-YAML dose fields
# (`IU`, `mcg`, `u`). We keep the human display as-is on `Quantity.unit`
# (clinicians reading the JSON see the familiar spelling) and map the
# machine `Quantity.code` field to the UCUM canonical form.
#
# Sources for the mapping: UCUM specification §32-35 (Common Units,
# Special Units) at https://ucum.org/ucum#section-Special-Units-On-Non-Ratio-Scales
# — the bracketed forms (`[iU]`, `[meq]`) are the "arbitrary units"
# convention UCUM reserves for quantities defined by biological assay.
# UCUM defines `U` (Unit, uppercase) as a generic enzymatic activity
# unit; the informal lowercase `u` clinicians write for insulin doses
# lands on the same UCUM concept.
#
# Only include tokens that clinosim actually emits (verified against
# the 2026-07-17 validation report). Adding a token that never appears
# is dead code; missing one leaves an error path open. Extension policy:
# add a new token here + a per-token pin test in
# tests/unit/output/test_ucum_code_canonicalization.py.
@cache
def _ucum_aliases() -> dict[str, str]:
    """The clinosim-emitted token → UCUM canonical code map. Rationale,
    extension policy, and authority source live in the yaml header; see
    codes/data/ucum-aliases.yaml."""
    path = Path(__file__).parent / "data" / "ucum-aliases.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {str(k): str(v) for k, v in (raw.get("aliases", {}) or {}).items()}


def ucum_code(unit: str) -> str:
    """Return the UCUM canonical code for a clinical unit string.

    Handles both scalar (``mcg``, ``IU``, ``u``) and compound (``mcg/kg``,
    ``IU/L``, ``0.1U/kg/h``) forms by splitting on ``/`` and mapping each
    factor independently; unknown factors are passed through, so ``mg/dL``,
    ``mL/h``, ``mmol/L`` are byte-identical.

    Idempotent — passing an already-canonical form (``[iU]/L``) returns it
    unchanged.
    """
    if not unit:
        return unit
    aliases = _ucum_aliases()
    if "/" not in unit:
        return aliases.get(unit, unit)
    return "/".join(aliases.get(p, p) for p in unit.split("/"))


def ucum_quantity(value: Any, unit: str, *, code: str | None = None) -> dict[str, Any]:
    """Build a FHIR ``Quantity`` (UCUM) with ``value``, ``unit`` (display), and ``code``.

    JP-CLINS ``JP_MedicationAdministration_eCS`` (and related eCS profiles) declare
    ``Quantity.code`` as ``min=1`` bound to UCUM; the FHIR-R4 UCUM idiom is that
    ``unit`` carries the human-readable label and ``code`` carries the machine
    UCUM token. Most clinical unit strings used by clinosim (``mg`` / ``mL`` /
    ``g/dL`` / ``mL/h`` / ``mmol/L`` / ``U/L`` ...) are already valid UCUM
    tokens, so ``unit`` and ``code`` end up identical; ``_to_ucum_code``
    handles the small set of informal spellings (``mcg`` → ``ug``,
    ``IU`` → ``[iU]``, ``u`` → ``U``, ``mEq`` → ``meq``, ``mmHg`` →
    ``mm[Hg]``) that UCUM rejects.

    Introduced (2026-07-16, PR-A) so every UCUM Quantity site — MA.dose,
    MA.rateQuantity, MR.dosageInstruction[].doseAndRate[].doseQuantity,
    Observation.referenceRange.low/high — goes through one edit point.
    Extended (2026-07-17, issue #204) with the ``_UCUM_CODE_MAP``
    normalization to close the remaining 6,203 unknown-code errors from
    the fhir-jp-validator 2026-07-17 report §【最優先 1】.

    ``code`` overrides the UCUM code when the display unit is a word rather
    than a unit token (a supply duration shown as "days" / "日" with code
    ``d``). Issue #2265: every FHIR Quantity is built here.
    """
    q: dict[str, Any] = {"value": value, "system": get_system_uri("ucum")}
    if unit:
        q["unit"] = unit
        q["code"] = code or ucum_code(unit)
    return q


def ucum_prose(unit: str | None) -> str:
    """Return a display-friendly form of a UCUM unit for prose (narrative,
    LLM context, DiagnosticReport.conclusion); FHIR Quantities keep the
    UCUM code (Issue #2267).

    UCUM allows dimensionless-annotation units of the form ``{annotation}``
    (curly braces are literal) — e.g. ``{INR}`` for PT-INR ratio,
    ``{score}`` for scored assessments — and lets any real unit carry a
    trailing ``/{annotation}`` clarifier (e.g. eGFR
    ``mL/min/{1.73_m2}``). These read as raw placeholders in narrative
    prose (``PT-INR 2.6 {INR}``, ``mL/min/{1.73_m2}``).

    Rules:
    - A pure-annotation unit ``{...}`` is treated as dimensionless and
      returns ``""`` — the accompanying value is self-describing.
    - A composite unit ``<real>/{...}`` strips the annotation clause
      (returns ``<real>``); the mL/min/1.73m² special-case is handled
      at its callsite for the ² typography, so this helper leaves the
      raw underscore/digit form untouched.
    - UCUM special-unit brackets ``[X]`` (e.g. ``mm[Hg]`` for mmHg,
      ``cm[H2O]`` for cmH2O) are stripped so blood-gas / airway-
      pressure units render as clinicians write them (`PaCO2 46.4
      mmHg` rather than `PaCO2 46.4 mm[Hg]`).
    - Otherwise the unit is returned verbatim.
    """
    if not unit:
        return ""
    u = str(unit).strip()
    if not u:
        return ""
    if u.startswith("{") and u.endswith("}"):
        return ""
    # Strip a trailing "/{annotation}" clause without touching the real
    # unit prefix.
    if u.endswith("}"):
        anno_start = u.rfind("/{")
        if anno_start > 0:
            u = u[:anno_start]
    # Strip UCUM special-unit brackets — `mm[Hg]` → `mmHg`,
    # `cm[H2O]` → `cmH2O`, `[in_i]` → `in_i`. The brackets carry no
    # information beyond marking a UCUM special unit family; prose
    # renders them without.
    if "[" in u and "]" in u:
        u = u.replace("[", "").replace("]", "")
    return u
