"""Lab-Observation code.coding[] strategy dispatch (JP-CLINS migration).

Migration chain (session 67 memo):

- **PR 1 (this file)** — introduce ``LabCodingKind`` enum + strategy
  protocol + 5 concrete strategies, refactor
  ``_fhir_observations._build_lab_observation`` to dispatch through
  ``select_lab_coding_strategy``. **byte-identical** guarantee: JP
  cohorts route to ``LegacyJSLMStrategy``, US cohorts to
  ``LegacyLOINCStrategy`` — both reproduce the pre-refactor inline
  emit exactly. No new coding kind is activated.
- **PR 2** — pkg installer + shared eCS SD loader (factors the axis
  runtime extractor). Enables the CoreLabo classification lookup.
- **PR 3** — implement ``CoreLaboStrategy`` real emit (session 67 memo
  §H.3 rev: 998-preferred code selection + material match + specimen
  back-derivation) + ``UncodedStrategy`` activation + LocalCode slice
  emit + display sanitization. Replaces the ``_classify_analyte``
  placeholder with real classification.
- **PR 4** — LOINC secondary retention decision on JP (JP Core parent
  binding is preferred, not required, so deletion is compliant).
- **PR 5** — CI invariant gate (axis 3 metrics == 100 %).

Enum stability
--------------
``LabCodingKind`` members are **fixed for the migration chain**.
Adding a new member is a breaking change to the dispatcher contract
and MUST come with a matching ``LabCodingStrategy`` implementation in
the same PR. This is why the enum is finalized in PR 1 rather than
extended incrementally — the placeholder dispatcher ships with all 5
targets and the classifier grows into them, so downstream call sites
never see an enum-widening event.

PR 1 invariant: ``emit_localcode_coding`` returns ``None``
-----------------------------------------------------------
Every strategy's ``emit_localcode_coding`` MUST return ``None`` in
PR 1. LocalCode slice emission is the byte-identical break point —
adding a LocalCode coding to any ``code.coding[]`` list would shift
downstream NDJSON hashes even if primary coding is unchanged. The
protocol carries the method so PR 3 can activate it without protocol
churn, but PR 1 relies on every strategy returning ``None`` here.
``tests/unit/test_lab_coding_strategy.py`` pins this per-strategy.

InfectionLabo policy
--------------------
``InfectionLaboStrategy.emit_codings`` **raises**
``NotImplementedError`` in PR 1..5. Returning an Uncoded coding as a
fallback would be a JP-CLINS spec violation (「感染症 5 項目該当なら
共有項目 JLAC code 必須」) and would silently look compliant. See
TODO ``T67-I1`` / ``T67-M1``. The classifier does not currently route
to this kind (production data emits 0 InfectionLabo-eligible
analytes), but if a call site ever selects this kind, failing loudly
is safer than emitting a wrong coding.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules._shared import is_us, resolve_lang

# --------------------------------------------------------------------------- #
# Kind enum — finalized in PR 1, extended only with matching strategy.


class LabCodingKind(StrEnum):
    """Which JP-CLINS lab coding strategy applies to a given
    (analyte, country) pair. See module docstring for stability policy."""

    CORELABO_JLAC10 = "corelabo_jlac10"
    INFECTION_LABO_JLAC10 = "infection_labo_jlac10"
    UNCODED = "uncoded"
    LEGACY_JSLM = "legacy_jslm"
    LEGACY_LOINC = "legacy_loinc"


# --------------------------------------------------------------------------- #
# Strategy protocol.


class LabCodingStrategy(Protocol):
    """Emits ``Observation.code.coding[]`` contents for a single lab
    result. Two hooks: ``emit_codings`` returns the primary (+ optional
    secondary) codings; ``emit_localcode_coding`` returns the LocalCode
    slice coding (or ``None`` in PR 1)."""

    kind: LabCodingKind

    def emit_codings(
        self,
        *,
        lab_name: str,
        order: dict,
        result: dict,
        country: str,
    ) -> list[dict]:
        """Return the primary + any secondary codings. Must be
        non-empty; caller uses ``codings[0]['code']`` as the primary
        code value for downstream profile-stack checks."""

    def emit_localcode_coding(
        self,
        *,
        lab_name: str,
        order: dict,
        result: dict,
        country: str,
    ) -> dict | None:
        """Return the LocalCode slice coding or ``None``.

        **PR 1 invariant**: every implementation MUST return ``None``.
        This is what makes the byte-identical guarantee hold across
        the strategy pattern refactor. PR 3 will introduce non-None
        returns from ``CoreLaboStrategy`` / ``UncodedStrategy`` /
        ``InfectionLaboStrategy``; ``LegacyJSLMStrategy`` /
        ``LegacyLOINCStrategy`` stay at ``None`` forever (they carry
        no LocalCode semantics)."""


# --------------------------------------------------------------------------- #
# Concrete strategies.


class LegacyJSLMStrategy:
    """JP pre-migration primary coding — reproduces the exact behavior
    of ``_build_lab_observation`` prior to PR 1 (JSLM generic OID
    primary + optional LOINC secondary). This is the byte-identical
    reference the strategy pattern refactor replaces the inline code
    with. It stays in the module after PR 3 as the default fallback
    for JP analytes that do not fit CoreLabo / InfectionLabo /
    Uncoded — analytes for which the pre-migration coding remains
    the most accurate available emit."""

    kind = LabCodingKind.LEGACY_JSLM

    def emit_codings(
        self,
        *,
        lab_name: str,
        order: dict,
        result: dict,
        country: str,
    ) -> list[dict]:
        code_map = load_code_mapping("lab", "JP")
        if lab_name in code_map:
            code_value = code_map[lab_name]
            code_system_key = system_key_for("lab", "JP")
        else:
            # Unmapped: fall back to raw order_code under LOINC (matches
            # pre-refactor behavior — mapping the code under jlac10 would
            # produce an incoherent coding).
            code_value = order.get("order_code", "")
            code_system_key = "loinc"
        lang = resolve_lang("JP")
        display_name = code_lookup(code_system_key, code_value, lang) if code_value else None
        if not display_name or display_name == code_value:
            display_name = lab_name
        primary: dict[str, Any] = {
            "system": get_system_uri(code_system_key),
            "code": code_value,
            "display": display_name,
        }
        codings: list[dict] = [primary]
        # JP dual coding: append LOINC secondary when a US-side mapping exists
        # and it differs from the primary code_value.
        us_code_map = load_code_mapping("lab", "US")
        loinc_code = us_code_map.get(lab_name)
        if loinc_code and loinc_code != code_value:
            loinc_display = code_lookup("loinc", loinc_code, "en") or lab_name
            codings.append(
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc_code,
                    "display": loinc_display,
                }
            )
        return codings

    def emit_localcode_coding(self, **_kwargs: Any) -> dict | None:
        # PR 1 invariant + long-term policy: LegacyJSLM never emits
        # LocalCode. The eCS LocalCode slice is a CoreLabo-family
        # concept.
        return None


class LegacyLOINCStrategy:
    """US primary coding — LOINC via ``code_mapping_lab.yaml``."""

    kind = LabCodingKind.LEGACY_LOINC

    def emit_codings(
        self,
        *,
        lab_name: str,
        order: dict,
        result: dict,
        country: str,
    ) -> list[dict]:
        code_map = load_code_mapping("lab", "US")
        if lab_name in code_map:
            code_value = code_map[lab_name]
            code_system_key = system_key_for("lab", "US")
        else:
            code_value = order.get("order_code", "")
            code_system_key = "loinc"
        lang = resolve_lang("US")
        display_name = code_lookup(code_system_key, code_value, lang) if code_value else None
        if not display_name or display_name == code_value:
            display_name = lab_name
        return [
            {
                "system": get_system_uri(code_system_key),
                "code": code_value,
                "display": display_name,
            }
        ]

    def emit_localcode_coding(self, **_kwargs: Any) -> dict | None:
        # US path never emits LocalCode (eCS is JP-only).
        return None


class UncodedStrategy:
    """JP-CLINS Uncoded slice — placeholder for PR 3 activation.

    Raises ``NotImplementedError`` in PR 1 because the classifier
    (``_classify_analyte``) does not route to this kind yet, so any
    call site reaching here would indicate an unexpected dispatcher
    path — better to fail loudly than to fabricate a coding."""

    kind = LabCodingKind.UNCODED

    def emit_codings(
        self,
        *,
        lab_name: str,
        order: dict,
        result: dict,
        country: str,
    ) -> list[dict]:
        raise NotImplementedError(
            f"UncodedStrategy is not activated in PR 1 (analyte={lab_name!r}). "
            "PR 3 will implement the JP-CLINS Uncoded slice emission "
            "(system=JP_CLINS_ObsLabResult_Uncoded_CS, code=99999999999999999, "
            "display='未標準化コード項目(JLAC)')."
        )

    def emit_localcode_coding(self, **_kwargs: Any) -> dict | None:
        return None


class InfectionLaboStrategy:
    """Deferred — JANIS master mapping required (TODO T67-M1).

    In PR 1..5, calling ``emit_codings`` MUST raise
    ``NotImplementedError``. Returning an Uncoded fallback would be a
    JP-CLINS spec violation (「感染症 5 項目該当なら共有項目 JLAC code
    必須」) and would silently look compliant. Explicit failure is
    safer. See TODO ``T67-I1``."""

    kind = LabCodingKind.INFECTION_LABO_JLAC10

    def emit_codings(
        self,
        *,
        lab_name: str,
        order: dict,
        result: dict,
        country: str,
    ) -> list[dict]:
        raise NotImplementedError(
            f"InfectionLaboStrategy is not implemented (analyte={lab_name!r}). "
            "See TODO T67-M1 / T67-I1. Falling back to UncodedStrategy would "
            "be a JP-CLINS spec violation — the applicability rule requires "
            "共有項目 JLAC code for infection-serology results, not Uncoded."
        )

    def emit_localcode_coding(self, **_kwargs: Any) -> dict | None:
        return None


class CoreLaboStrategy:
    """CoreLabo JLAC10 slice — PR 1 wrapper delegating to
    ``LegacyJSLMStrategy`` for byte-identical output.

    PR 3 replaces the delegation with the real 17-digit code selection
    (session 67 memo §H.3 rev: 998-preferred method + material-match
    → code chosen first → specimen back-derived) and non-None
    ``emit_localcode_coding`` for the LocalCode slice."""

    kind = LabCodingKind.CORELABO_JLAC10

    def __init__(self) -> None:
        self._delegate = LegacyJSLMStrategy()

    def emit_codings(
        self,
        *,
        lab_name: str,
        order: dict,
        result: dict,
        country: str,
    ) -> list[dict]:
        # PR 1: byte-identical delegation. Replace in PR 3.
        return self._delegate.emit_codings(lab_name=lab_name, order=order, result=result, country=country)

    def emit_localcode_coding(self, **_kwargs: Any) -> dict | None:
        # PR 3 will emit LocalCode; PR 1 returns None for byte-identical.
        return None


# --------------------------------------------------------------------------- #
# Dispatcher.


def _classify_analyte(lab_name: str, country: str) -> LabCodingKind:
    """Placeholder in PR 1 — returns ``LEGACY_*`` to preserve
    byte-identical output. PR 3 will replace with real classification:

    - JP + analyte in CoreLabo 55-parent set → ``CORELABO_JLAC10``
    - JP + analyte in InfectionLabo 5-item set → ``INFECTION_LABO_JLAC10``
    - JP + otherwise → ``UNCODED`` (with LocalCode always co-emitted)
    - US → ``LEGACY_LOINC`` (unchanged)

    The lookup table for CoreLabo / InfectionLabo membership is
    supplied by the shared pkg loader (PR 2 factors this from
    ``clinosim/eval/axes/jp_clins_lab_compliance._load_slice_map``).
    """
    if is_us(country):
        return LabCodingKind.LEGACY_LOINC
    return LabCodingKind.LEGACY_JSLM


_STRATEGIES: dict[LabCodingKind, LabCodingStrategy] = {
    LabCodingKind.LEGACY_JSLM: LegacyJSLMStrategy(),
    LabCodingKind.LEGACY_LOINC: LegacyLOINCStrategy(),
    LabCodingKind.CORELABO_JLAC10: CoreLaboStrategy(),
    LabCodingKind.INFECTION_LABO_JLAC10: InfectionLaboStrategy(),
    LabCodingKind.UNCODED: UncodedStrategy(),
}


def select_lab_coding_strategy(lab_name: str, country: str) -> LabCodingStrategy:
    """Look up the strategy for this (analyte, country) pair. Uses
    ``_classify_analyte`` to determine ``LabCodingKind`` and returns
    the corresponding singleton strategy."""
    kind = _classify_analyte(lab_name, country)
    return _STRATEGIES[kind]
