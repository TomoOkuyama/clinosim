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
from clinosim.modules.output.lab_coding_package import LabCodeCandidate

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
    """CoreLabo JLAC10 slice — PR 3b real emit.

    Session 67 memo §H.3 rev + user judgment (Option B, 2026-07-26):
    - method priority: ``998`` (method-agnostic, "測定法問わず" — the
      most honest choice given clinosim does not simulate specific
      measurement methods) → fallback ``999`` (other) → fallback any
    - material priority: numerically-largest material code (Option B)
      — for chemistry analytes this resolves to 023 (血清 serum) which
      matches Japanese standard-lab practice; for hematology-only
      analytes (WBC / Plt) there is only one material (019 EDTA whole
      blood) so the rule is vacuous
    - specimen back-derivation: the chosen code's material segment IS
      the JP_ObservationSampleMaterialCodeJLAC10_CS code (1-1 mapping,
      verified session 67 2026-07-26 — no translation table needed)

    Also carries the LOINC secondary co-emission from ``LegacyJSLMStrategy``
    to preserve the JP dual-coding invariant (JLAC primary + LOINC
    interop, per DESIGN Global-symmetry principle; PR 4 will make the
    LOINC retain/drop decision explicit).

    Requires an installed JP-CLINS pkg (falls back to LegacyJSLM
    emission when the pkg is not available, so cohorts generated on a
    minimal install still get some coding rather than crash)."""

    kind = LabCodingKind.CORELABO_JLAC10

    def __init__(self) -> None:
        # Kept for the pkg-absent fallback path — CoreLabo emit requires
        # the eCS SD + CoreLabo CS from the JP-CLINS pkg; if either is
        # missing we defer to LegacyJSLM rather than crash mid-generate.
        self._legacy = LegacyJSLMStrategy()

    def emit_codings(
        self,
        *,
        lab_name: str,
        order: dict,
        result: dict,
        country: str,
    ) -> list[dict]:
        from clinosim.modules.output.lab_coding_package import load_lab_coding_package

        slice_name = _slice_name_for_analyte(lab_name)
        pkg = load_lab_coding_package()
        if slice_name is None or not pkg.is_available():
            # Defensive fallback — classifier should never route here without
            # a slice mapping, but if pkg missing we can't emit CoreLabo codes.
            return self._legacy.emit_codings(lab_name=lab_name, order=order, result=result, country=country)
        slice_info = pkg.slice_info(f"coreLaboJLAC10/{slice_name}")
        if slice_info is None or not slice_info.codes:
            return self._legacy.emit_codings(lab_name=lab_name, order=order, result=result, country=country)

        chosen = _pick_corelabo_code(slice_info.codes)
        # Primary CoreLabo coding — Fixed display MUST come from the SD,
        # NOT designation_ja (session 67 dual-slot rule: coding.display =
        # canonical Fixed value, JP text goes into LocalCode display /
        # code.text via PR 3c).
        primary: dict[str, Any] = {
            "system": slice_info.slice_system,
            "code": chosen.code,
            "display": slice_info.fixed_display,
        }
        codings: list[dict] = [primary]
        # JP dual coding: keep LOINC secondary (mirrors LegacyJSLM's
        # dual-emit; PR 4 will formalize the retain decision as an ADR).
        us_code_map = load_code_mapping("lab", "US")
        loinc_code = us_code_map.get(lab_name)
        if loinc_code:
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
        # PR 3c will emit LocalCode co-slice; PR 3b keeps None so this
        # PR moves only Metric 1 (CS 使用率) + Metric 2 (Fixed display).
        # Metric 3 (適用規則満足率) intentionally stays 0/2509 until 3c.
        return None


def _pick_corelabo_code(codes: tuple[LabCodeCandidate, ...]) -> LabCodeCandidate:
    """Session 67 memo §H.3 rev + user Option B judgment (2026-07-26).

    1. Filter to ``method='998'`` (method-agnostic, the honest default
       for synthetic data that does not simulate specific methods).
       Fallback to ``method='999'`` (other) if no 998 exists;
       final fallback to any code (should not trigger — all 20
       CoreLabo analytes have 998 codes per session 67 pre-cover).
    2. Among the filtered candidates, pick the numerically-largest
       material code (Option B — for chemistry this resolves to 023
       血清 which matches standard Japanese lab practice).
    3. Within material + method, deterministic sort by full code for
       reproducibility across runs.
    """
    m998 = [c for c in codes if c.segments.method == "998"]
    pool = m998 or [c for c in codes if c.segments.method == "999"] or list(codes)
    # Numerically-largest material — Option B
    max_material = max(c.segments.material for c in pool)
    same_material = [c for c in pool if c.segments.material == max_material]
    # Deterministic tiebreak inside same material + method: sort by full code
    return sorted(same_material, key=lambda c: c.code)[0]


# --------------------------------------------------------------------------- #
# Classifier — clinosim analyte-name → coding kind (clinosim IP).
#
# This is the ONLY place clinosim-side mapping lives (per session 67
# memo license boundary: SD/CS-derived data stays in
# ``lab_coding_package``; clinosim's own analyte name → SD slice_name
# lookup stays here, commit-safe).
#
# PR 3a scope: classifier is implemented + unit-tested but NOT yet
# consumed by ``select_lab_coding_strategy`` (dispatcher is 1-line
# unchanged for byte-identical guarantee). PR 3b will bridge the
# classifier result into the dispatcher for CoreLabo-eligible analytes;
# PR 3c bridges Uncoded. Until then, the classifier's return values
# are verified by unit tests alone — production callsites of the
# dispatcher never see the new classification.


# clinosim internal analyte name → SD slice suffix (SD slice name is
# ``coreLaboJLAC10/<suffix>``). 20 entries — every JP analyte that
# resolves to a CoreLabo slice today.
#
# Glucose is INTENTIONALLY absent here — it maps to Uncoded (see below)
# because the upstream simulator does not carry fasting_state, so
# distinguishing BG / FBG / CBG is not currently possible. See TODO
# ``T67-Glucose-disambig``. Assigning Glucose to any single CoreLabo
# slice (e.g. ``bg``) would fabricate a semantic identity the data
# does not support (some emitted glucose is legitimately fasting or
# capillary); Uncoded is the honest classification under uncertainty.
_ANALYTE_TO_SLICE_NAME: dict[str, str] = {
    "Creatinine": "cre",
    "K": "k",
    "Na": "na",
    "WBC": "wbc",
    "AST": "ast",
    "ALT": "alt",
    "CRP": "crp",
    "Hb": "hb",
    "BUN": "bun",
    "PT_INR": "pt-inr",
    "BNP": "bnp",
    "Plt": "plt",
    "Ca": "ca",
    "Albumin": "alb",
    "HbA1c": "hba1c-ngsp",
    "TG": "tg",
    "HDL": "hdl-c",
    "TC": "t-cho",
    "APTT": "aptt",
    "D_dimer": "dd",
}

# clinosim analytes explicitly known to have no CoreLabo slice —
# routed to Uncoded (spec-compliant fallback for standardization-not-possible).
# Enumerated (not implicit) so a NEW analyte added to the pipeline
# without a mapping decision triggers the completeness test in
# ``tests/unit/test_lab_coding_strategy.py`` — unmapped→UNCODED default
# is a safety net for the runtime, not a mechanism for silent takedowns.
_KNOWN_UNCODED_ANALYTES: frozenset[str] = frozenset(
    {
        # Arterial blood gas (4)
        "pH",
        "pCO2",
        "pO2",
        "HCO3",
        # Cardiac markers not in CoreLabo (2)
        "Troponin_I",
        "CK_MB",
        # Metabolic / infection markers (5)
        "Lactate",
        "PCT",
        "TSH",
        "Fibrinogen",
        "eGFR",
        # Glucose — needs disambig into bg/fbg/cbg but upstream does not
        # carry fasting_state today. Uncoded until T67-Glucose-disambig
        # lands data-pipeline changes.
        "Glucose",
    }
)


def _slice_name_for_analyte(lab_name: str) -> str | None:
    """Return the SD slice suffix (e.g. ``k`` for
    ``coreLaboJLAC10/k``) for a clinosim internal analyte name.
    Returns ``None`` for analytes with no CoreLabo slice — those route
    to Uncoded via ``_classify_analyte``."""
    return _ANALYTE_TO_SLICE_NAME.get(lab_name)


def _classify_analyte(lab_name: str, country: str) -> LabCodingKind:
    """PR 3a real classifier. Return the coding kind for this
    (analyte, country) pair.

    - US → ``LEGACY_LOINC`` (unchanged; LOINC direct mapping remains)
    - JP + analyte in ``_ANALYTE_TO_SLICE_NAME`` → ``CORELABO_JLAC10``
    - JP + analyte in ``_KNOWN_UNCODED_ANALYTES`` → ``UNCODED``
    - JP + analyte NOT in either set → ``UNCODED`` (safe fallback for
      unrecognised analytes; the completeness test in unit tests
      guards against silent takedowns of known analytes)

    **NOTE (PR 3a invariant)**: this function is only called from
    unit tests in PR 3a. ``select_lab_coding_strategy`` does not
    invoke it yet — the dispatcher continues to return LegacyJSLM /
    LegacyLOINC unchanged for byte-identical production output.
    PR 3b bridges CoreLabo-classified analytes; PR 3c bridges Uncoded.
    """
    if is_us(country):
        return LabCodingKind.LEGACY_LOINC
    if lab_name in _ANALYTE_TO_SLICE_NAME:
        return LabCodingKind.CORELABO_JLAC10
    return LabCodingKind.UNCODED


_STRATEGIES: dict[LabCodingKind, LabCodingStrategy] = {
    LabCodingKind.LEGACY_JSLM: LegacyJSLMStrategy(),
    LabCodingKind.LEGACY_LOINC: LegacyLOINCStrategy(),
    LabCodingKind.CORELABO_JLAC10: CoreLaboStrategy(),
    LabCodingKind.INFECTION_LABO_JLAC10: InfectionLaboStrategy(),
    LabCodingKind.UNCODED: UncodedStrategy(),
}


def select_lab_coding_strategy(lab_name: str, country: str) -> LabCodingStrategy:
    """Look up the strategy for this (analyte, country) pair.

    **PR 3b bridge** (session 67 2026-07-26): US → LegacyLOINC, JP →
    consult ``_classify_analyte``. CoreLabo-classified analytes route
    to ``CoreLaboStrategy`` (real 17-digit + Fixed display emit).
    Uncoded and unmapped-JP still route to ``LegacyJSLMStrategy`` to
    preserve byte-identical output for those paths — PR 3c will bridge
    Uncoded and retire the JP LegacyJSLM path.

    byte-partial guarantee for PR 3b: only ``_classify_analyte(...) ==
    CORELABO_JLAC10`` analytes have their emit changed. Uncoded /
    LegacyJSLM-classified analytes (611 obs on v30 JP CIF) stay
    byte-identical vs PR 3a.
    """
    if is_us(country):
        return _STRATEGIES[LabCodingKind.LEGACY_LOINC]
    kind = _classify_analyte(lab_name, country)
    if kind == LabCodingKind.CORELABO_JLAC10:
        return _STRATEGIES[LabCodingKind.CORELABO_JLAC10]
    # UNCODED and anything else on JP → LegacyJSLM (unchanged, PR 3c bridge)
    return _STRATEGIES[LabCodingKind.LEGACY_JSLM]
