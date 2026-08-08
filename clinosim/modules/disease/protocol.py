"""Disease protocol loader and data structures."""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

# reference_data is in the same package: clinosim/modules/disease/reference_data/
_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


# ---------------------------------------------------------------------------
# Drug-block route fallback validation (Issue #455)
# ---------------------------------------------------------------------------
#
# Two readers in `clinosim/simulator/inpatient.py` substitute a route when a
# drug entry omits the `route` key. Each substitutes a different default:
#
#   drugs.discharge_oral -> "PO"   (`_build_discharge_rx._append_item`)
#   drugs.escalation     -> "IV"   (escalation order placement)
#
# The substitution is a grounded inference for most entries — `discharge_oral`
# is named "oral" and its doses usually say `PO`; `escalation` doses usually say
# `IV`. It becomes a FALSE ASSERTION only when the entry's own dose string names
# a route set that EXCLUDES the fallback (e.g. `2000IU SC daily` under `PO`).
#
# The check is therefore fallback-RELATIVE. A non-relative rule ("dose contains a
# non-oral token") would reject 38 shipped `escalation` entries whose dose says
# `IV` under an `IV` fallback — cases where the fallback is producing the right
# answer.
#
# Blocks absent from this table are NOT validated, deliberately:
#   * `first_line` has a reader but substitutes "" (no assertion to contradict).
#   * `post_op` / `alternative_penicillin_allergy` / `mrsa_coverage` /
#     `hyperkalemia_management` / `alternative_beta_blocker_contraindicated`
#     have ZERO Python readers (Issue #437 dead-data class) — no fallback exists,
#     so there is nothing to contradict, and validating them would fail the build
#     for data that never reaches output.
# Adding a third substituting reader means adding it here in the same change.
DRUG_BLOCK_ROUTE_FALLBACKS: dict[str, str] = {
    "discharge_oral": "PO",
    "escalation": "IV",
}

# Route abbreviations that appear inside free-text `dose` strings.
#
# PO is included deliberately, as a *forward* defense — it changes no verdict today.
# The fallback-relative test asks "is the fallback among the routes this dose names",
# so a dose that names the fallback ALONGSIDE another route must not read as a
# contradiction. Dual-route doses do exist in the corpus — e.g.
# `hyperkalemia_management` `15-30g PO or PR`, `first_line` `20-40mg IV or PO daily`,
# `alternative_penicillin_allergy` `500mg IV or PO daily` — but none currently sit in
# a block listed in DRUG_BLOCK_ROUTE_FALLBACKS, so measured impact is 0 entries
# (verified: 0 of the 123 route-less entries in the checked blocks name more than one
# route, and 0 change verdict if PO is dropped from this tuple). The tuple stays
# PO-inclusive so that a dual-route dose landing in a checked block later — or a
# currently-dead block gaining a reader and a fallback — cannot be mis-flagged.
ROUTE_DOSE_TOKENS: tuple[str, ...] = (
    "PO",
    "IV",
    "SC",
    "IM",
    "SL",
    "PR",
    "NG",
    "TD",
    "INH",
    "NEB",
)

# Word boundaries are load-bearing. Substring matching false-positives on 10
# shipped entries: 9 PRN (as-needed) doses where `PR` sits inside `PRN`, and one
# `NG` inside "remaining days of 5-day course". That is the same defect class as
# the `_determine_route` substring flaw (`"IV" in "Rivaroxaban"`), so this guard
# must not reintroduce it — see
# tests/unit/test_discharge_oral_route_integrity.py negative cases.
_ROUTE_DOSE_RE = re.compile(r"\b(" + "|".join(ROUTE_DOSE_TOKENS) + r")\b", re.IGNORECASE)


def dose_route_tokens(dose: str) -> set[str]:
    """Return the uppercased route abbreviations named in a free-text dose string.

    Word-boundary matched, so `PRN` yields no `PR` and `remaining` yields no `NG`.
    Returns an empty set when the dose names no route (e.g. "Resume or initiate
    controller therapy") — silence is not a contradiction.
    """
    return {m.upper() for m in _ROUTE_DOSE_RE.findall(dose or "")}


def dose_contradicts_fallback(dose: str, fallback: str) -> bool:
    """True when the dose string names route(s) and the fallback is not among them.

    A dose naming no route at all never contradicts: the block name remains the
    only evidence and the fallback is the best available inference.
    """
    named = dose_route_tokens(dose)
    return bool(named) and (fallback or "").upper() not in named


def _iter_route_values(data: Any) -> Iterator[str]:
    """Yield every `route:` string found anywhere in a nested YAML structure.

    Walks lists and dicts recursively; only picks up the value keyed exactly
    `route`. Sibling to `_validate_drug_route_consistency` — feeds the
    Issue #458 vocabulary check without hard-coding which drug blocks exist.
    """
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "route" and isinstance(v, str):
                yield v
            else:
                yield from _iter_route_values(v)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_route_values(item)


def _validate_drug_route_vocabulary(disease_id: str, data: dict[str, Any]) -> None:
    """Fail loudly when a disease YAML author uses a route value that isn't in
    the canonical / alias / by-design set (Issue #458).

    Pre-fix: `_ROUTE_SNOMED.get(route)` silently returned None for unknown
    values and the FHIR builder emitted `{"text": VALUE}` with no coding —
    the PR-90 silent-no-op class explicitly documented in CLAUDE.md §
    "Import-time canonical-constants validation". Adding a new value in a
    disease YAML would ship broken FHIR with no error until an audit ran.

    Delegates to `validate_yaml_route_value` so the recognized set stays
    single-sourced in `_fhir_reference_data.py`.
    """
    from clinosim.modules.output.fhir_r4.lib.reference_data import validate_yaml_route_value

    for raw in _iter_route_values(data):
        validate_yaml_route_value(raw, source=f"disease {disease_id!r}")


# ---------------------------------------------------------------------------
# Drug-block duration_days fallback validation (Issue #462)
# ---------------------------------------------------------------------------
#
# `_build_discharge_rx._append_item` substitutes `duration_days = 7` when a
# `discharge_oral` entry omits the field. That fallback is a grounded inference
# for daily-dosed drugs where "7 days = 1 week supply" is a defensible default.
#
# It becomes a FALSE ASSERTION when the entry's dose string names an
# administration interval **longer than one week** — a `q6months` dose gets 0
# doses in a 7-day supply, a `weekly` dose gets exactly 1 when a typical
# prescription supply is 3 months. Sibling to the route-fallback check
# (`_validate_drug_route_consistency`); same "空欄は無知、誤った断言は虚偽"
# principle: silence in the dose is acceptable (fallback = best guess), but a
# dose that names a long interval contradicts the 7-day default.
#
# Detection is conservative — only intervals unambiguously > 1 week fire.
# Daily / BID / TID / q4-6h etc. remain valid under the 7-day fallback.
_LONG_INTERVAL_RE = re.compile(
    r"\b(weekly|monthly|q\s*\d+\s*(weeks?|months?|weekly|monthly))\b",
    re.IGNORECASE,
)


def dose_names_long_interval(dose: str) -> bool:
    """True when the dose string names an administration interval > 1 week.

    Fires on: `weekly`, `monthly`, `q<N>weeks`, `q<N>months` (case-insensitive).
    Does NOT fire on: daily / BID / TID / q<N>h — those are within the 7-day
    fallback envelope. Returns False for empty / silence-only doses.
    """
    return bool(_LONG_INTERVAL_RE.search(dose or ""))


def _validate_drug_block_duration_days(disease_id: str, drugs: dict[str, Any]) -> None:
    """Fail loudly when a `discharge_oral` entry's dose names a long interval but
    omits `duration_days`, forcing the reader to substitute the 7-day fallback.

    Load-time (not runtime) on purpose — same rationale as
    `_validate_drug_route_consistency`. Sibling check; scoped to `discharge_oral`
    because that is the only block whose reader (`_append_item`) substitutes a
    numeric `duration_days` default. Escalation orders carry their own duration
    semantics (drip / titration) and are not covered here.
    """
    if not isinstance(drugs, dict):
        return
    block = drugs.get("discharge_oral")
    if not isinstance(block, dict):
        return
    offenders: list[str] = []
    for country_key in ("japan", "us"):
        entries = block.get(country_key) or []
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or "duration_days" in entry:
                continue
            dose = str(entry.get("dose", "") or "")
            if dose_names_long_interval(dose):
                offenders.append(
                    f"  drugs.discharge_oral.{country_key}: drug={entry.get('drug', '')!r} "
                    f"dose={dose!r} names an interval longer than the 7-day fallback "
                    f"but omits `duration_days`, so the reader would substitute `7`."
                )
    if offenders:
        raise ValueError(
            f"disease {disease_id!r}: dose string names a long administration interval "
            f"but no `duration_days` is declared (Issue #462). Declare an explicit "
            f"`duration_days` on each entry below so the reader does not assert a "
            f"7-day supply that contradicts the dose interval:\n" + "\n".join(offenders)
        )


def _validate_drug_route_consistency(disease_id: str, drugs: dict[str, Any]) -> None:
    """Fail loudly when an absent-`route` entry's dose contradicts its block fallback.

    Load-time (not runtime) on purpose: the data is entirely YAML-sourced, so every
    offender is decidable before a single patient is simulated. Raising inside the
    per-patient `_append_item` path would surface the same defect only once the
    offending disease happened to be drawn.

    Issue #455: PR #457 fixed 4 entries but its sweep keyed on drug-NAME words, so
    Enoxaparin / Denosumab (whose route lives only in the dose string) were missed.
    """
    if not isinstance(drugs, dict):
        return
    offenders: list[str] = []
    for block_name, fallback in DRUG_BLOCK_ROUTE_FALLBACKS.items():
        block = drugs.get(block_name)
        if not isinstance(block, dict):
            continue
        for country_key in ("japan", "us"):
            entries = block.get(country_key) or []
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or "route" in entry:
                    continue
                dose = str(entry.get("dose", "") or "")
                if dose_contradicts_fallback(dose, fallback):
                    offenders.append(
                        f"  drugs.{block_name}.{country_key}: drug={entry.get('drug', '')!r} "
                        f"dose={dose!r} names route(s) {sorted(dose_route_tokens(dose))} "
                        f"but omits `route`, so the reader would assert route={fallback!r}"
                    )
    if offenders:
        raise ValueError(
            f"disease {disease_id!r}: dose string contradicts the absent-`route` fallback "
            f"(Issue #455). Declare an explicit `route` on each entry below:\n" + "\n".join(offenders)
        )


# ---------------------------------------------------------------------------
# Localized dose instruction key typo defense (Issue #476)
# ---------------------------------------------------------------------------
#
# `DiseaseProtocol.drugs` is `dict[str, Any]`, so `extra="forbid"` on the model
# does NOT guard drug-entry keys — a typo like `dose_jp` (instead of `dose_ja`)
# is silently swallowed by the reader's `.get("dose_ja", "")`. This validator
# catches the specific typos most likely to trip up authors extending the
# Issue #476 pattern to new drug entries.
_LOCALIZED_DOSE_KEY_TYPOS: dict[str, str] = {
    "dose_jp": "dose_ja",
    "dose_us": "dose_en",
    "dose_english": "dose_en",
    "dose_japanese": "dose_ja",
    "ja_dose": "dose_ja",
    "en_dose": "dose_en",
}


# ---------------------------------------------------------------------------
# drugs.escalation type signal validation (Issue #460)
# ---------------------------------------------------------------------------
#
# `drugs.escalation[*]` may declare an explicit `type` field to signal whether
# the entry is a medication order or a procedure order. When present, the value
# must be exactly `"medication"` or `"procedure"` (Layer 1 in this module).
#
# Consumed by `clinosim/simulator/inpatient.py` via
# `classify_escalation_treatment`, which routes on `type` in preference to the
# text-substring keyword fallback. Design:
# `docs/superpowers/specs/2026-08-07-drugs-escalation-procedure-signal-design.md`.
#
# Layers 2 (legacy marker reject) and 3 (`type=procedure` + `route` reject) are
# added in a follow-up commit after the 3 shipped YAMLs are migrated.
_ALLOWED_ESCALATION_TYPES: frozenset[str] = frozenset({"medication", "procedure"})


def _validate_escalation_type_signal(disease_id: str, drugs: dict[str, Any]) -> None:
    """3-layer validation of drugs.escalation[*] entries (Issue #460).

    Layer 1: `type` field, if present, must be one of {"medication", "procedure"}.
    Layer 2: pre-Issue-460 legacy marker `code_yj: "procedure"|"N/A"` or
             `code_rxnorm: "procedure"|"N/A"` must be replaced with explicit
             `type: "procedure"` (the marker was YAML-author signal that the
             pre-refactor code did not read).
    Layer 3: `type: "procedure"` MUST NOT co-occur with a `route:` field.
             Procedure resource has no `route`; carrying one is a semantic
             contradiction that would confuse a downstream reader.
    """
    if not isinstance(drugs, dict):
        return
    escalation = drugs.get("escalation")
    if not isinstance(escalation, dict):
        return
    for country_key, entries in escalation.items():
        entry_list = entries if isinstance(entries, list) else [entries]
        for entry in entry_list:
            if not isinstance(entry, dict):
                continue
            drug_label = entry.get("drug", "")
            type_signal = entry.get("type")

            # Layer 1
            if type_signal is not None and type_signal not in _ALLOWED_ESCALATION_TYPES:
                raise ValueError(
                    f"drugs.escalation entry in disease {disease_id!r} has invalid "
                    f"type={type_signal!r} (country {country_key!r}, drug "
                    f"{drug_label!r}). Allowed: {sorted(_ALLOWED_ESCALATION_TYPES)}."
                )

            # Layer 2
            code_yj = entry.get("code_yj", "")
            code_rxnorm = entry.get("code_rxnorm", "")
            if code_yj in ("procedure", "N/A") or code_rxnorm in ("procedure", "N/A"):
                raise ValueError(
                    f"drugs.escalation entry in disease {disease_id!r} carries a "
                    f"legacy non-code marker (code_yj={code_yj!r}, "
                    f"code_rxnorm={code_rxnorm!r}) at country {country_key!r}, "
                    f'drug {drug_label!r}. Migrate to `type: "procedure"` and '
                    f"remove the marker (Issue #460)."
                )

            # Layer 3
            if type_signal == "procedure" and entry.get("route"):
                raise ValueError(
                    f"drugs.escalation entry in disease {disease_id!r} with "
                    f'type="procedure" must not carry a `route` field '
                    f"(Procedure resource has no route). Remove `route` from entry "
                    f"at country {country_key!r}, drug {drug_label!r}."
                )


def _validate_drug_entry_localized_dose_keys(disease_id: str, drugs: dict[str, Any]) -> None:
    """Fail loudly on likely typos of the `dose_ja` / `dose_en` keys (Issue #476).

    Load-time (not runtime) on purpose: the data is entirely YAML-sourced,
    so every offender is decidable before a single patient is simulated.
    Same class as `_validate_drug_route_consistency` / `_validate_drug_block_duration_days`.
    """
    if not isinstance(drugs, dict):
        return
    offenders: list[str] = []
    for block_name, block in drugs.items():
        if not isinstance(block, dict):
            continue
        for country_key in ("japan", "us"):
            entries = block.get(country_key) or []
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                for typo, canonical in _LOCALIZED_DOSE_KEY_TYPOS.items():
                    if typo in entry:
                        offenders.append(
                            f"  drugs.{block_name}.{country_key}: drug={entry.get('drug', '')!r} "
                            f"has key {typo!r} — did you mean {canonical!r}? "
                            f"(Issue #476 localized dose instruction key)"
                        )
    if offenders:
        raise ValueError(
            f"disease {disease_id!r}: localized dose instruction key typo(s) detected "
            f"(silent-drop risk — the reader would swallow the typo and emit no text):\n" + "\n".join(offenders)
        )


# ---------------------------------------------------------------------------
# Narrative spec models (Tier 1 #3 α-min-1 Task 4)
# ---------------------------------------------------------------------------


class PhysicalExamSystemFindings(BaseModel):
    """Severity-stratified physical exam findings for a single organ system.

    Use ``all`` for severity-agnostic findings (e.g. "整、心雑音なし").
    Use ``mild`` / ``moderate`` / ``severe`` for severity-specific wording.
    """

    mild: str = ""
    moderate: str = ""
    severe: str = ""
    all: str | None = None  # severity-agnostic override


class PhysicalExamDayFindings(BaseModel):
    """Physical exam findings for a single clinical day grouped by organ system."""

    general: PhysicalExamSystemFindings = Field(default_factory=PhysicalExamSystemFindings)
    cardiovascular: PhysicalExamSystemFindings = Field(default_factory=PhysicalExamSystemFindings)
    respiratory: PhysicalExamSystemFindings = Field(default_factory=PhysicalExamSystemFindings)
    abdominal: str = ""
    neurological: str = ""


class HpiTemplate(BaseModel):
    """HPI (history of present illness) template parameters."""

    onset_pattern: dict[str, str] = Field(default_factory=dict)  # mild/moderate/severe → text
    trigger_options: list[str] = Field(default_factory=list)


class DischargeInstructions(BaseModel):
    """Discharge instruction texts keyed by language (``en`` / ``ja``)."""

    follow_up: dict[str, str] = Field(default_factory=dict)
    activity: dict[str, str] = Field(default_factory=dict)
    medications: dict[str, str] = Field(default_factory=dict)
    emergency: dict[str, str] = Field(default_factory=dict)
    diet_lifestyle: dict[str, str] = Field(default_factory=dict)


class NarrativeSpec(BaseModel):
    """Top-level narrative specification stored under ``DiseaseProtocol.narrative``.

    Consumed by TemplateNarrativeGenerator (Task 6) to produce per-disease
    clinical narratives rather than generic boilerplate.
    ``physical_exam_findings`` maps:  archetype_name → day_str → PhysicalExamDayFindings
    """

    hpi_template: HpiTemplate = Field(default_factory=HpiTemplate)
    physical_exam_findings: dict[str, dict[str, PhysicalExamDayFindings]] = Field(default_factory=dict)
    discharge_instructions: DischargeInstructions = Field(default_factory=DischargeInstructions)


class DailyTrajectoryEntry(BaseModel):
    """SOAP-structured clinical note entry for a single inpatient day."""

    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""


class ImagingOrderSpec(BaseModel):
    """Imaging order entry inside DiseaseProtocol (Tier 1 #2 PR1).

    One entry = one imaging study ordered at a specific day in the admission.
    The imaging enricher (Task 4) uses ``abnormal_rate_by_severity`` to sample
    whether the study is normal or abnormal and pick an impression template.
    """

    modality: str
    body_site: str
    views: list[str] = Field(default_factory=list)
    urgency: str = "routine"
    clinical_indication: str = ""
    day: int = 0
    contrast: bool = False
    only_if_severity: list[str] = Field(default_factory=list)
    abnormal_rate_by_severity: dict[str, float] = Field(default_factory=dict)


class DiseaseProtocol(BaseModel):
    """Loaded disease protocol from YAML. Validated by Pydantic."""

    # Author-time defense against the C1 silent-drop class (FP-YAML-3): an unrecognized
    # top-level YAML key (typo or unwired field) raises at load instead of being dropped.
    model_config = ConfigDict(extra="forbid")

    disease_id: str
    icd_codes: dict[str, Any]
    incidence: dict[str, Any]
    severity: dict[str, Any]
    presenting_symptoms: list[dict[str, Any]] = []
    course_archetypes: dict[str, Any] = {}
    # Per-disease patient-risk-factor adjustments to archetype selection probabilities
    # (FP-YAML-2b). Consumed by select_archetype via _apply_archetype_modifiers.
    archetype_modifiers: list[dict[str, Any]] = []
    initial_state_impact: dict[str, dict[str, float]] = {}
    diagnostic: dict[str, Any] = {}
    order_protocols: dict[str, Any] = {}
    target_los: dict[str, Any] = {}
    complications: list[dict[str, Any]] = []
    likelihood_ratios: dict[str, Any] = {}
    expected_lab_distributions: dict[str, Any] = {}
    expected_vital_distributions: dict[str, Any] = {}
    drugs: dict[str, Any] = {}
    # NOTE (session 39): reference_ranges was removed — it duplicated the live
    # locale-side lab reference ranges (locale is the single source; AD-30). The
    # sibling authored-but-unwired blocks (drug_interactions below and
    # expected_vital_distributions at line 128) are RETAINED as future-wiring
    # seeds, not deleted: drug_interactions seeds the planned FHIR DetectedIssue
    # resource (docs/design-notes/2026-06-30-tier1-...-master-plan.md), and
    # expected_vital_distributions is a candidate target for the cohort-level
    # completeness audit axis (fix-point registry FP-COMPLETENESS-GATE).
    drug_interactions: list[dict[str, Any]] = []
    outcome_benchmarks: dict[str, Any] = {}

    # Disease metadata (eliminates hardcoding in simulator)
    chief_complaint: str | dict[str, str] = ""  # str or {en: "...", ja: "..."}
    department: str = "internal_medicine"
    encounter_type: str = "medical"  # "medical" | "surgical" | "trauma"
    requires_surgery: bool = False
    minimum_severity: str | None = None  # force minimum severity (e.g. "moderate" for fracture)
    readmission_eligible: bool = True  # False for surgical conditions like fractures
    procedure: dict[str, Any] = {}  # Surgical procedure details (approach, duration, etc.)
    medication_holds: list[dict[str, Any]] = []  # Home medications to hold during this admission
    # Acute coronary syndrome → primary myocardial necrosis (drives high troponin/CK-MB,
    # vs the mild type-2 elevation any cardiac dysfunction produces). AD-55.
    causes_myocardial_injury: bool = False
    # VTE-spectrum scenario flag (PE / DVT / embolic ischemic stroke): pushes
    # D-dimer into the clinically positive range. NOT for hemorrhagic_stroke
    # (intracerebral fibrinolysis is captured by coagulation_status alone),
    # and NOT for AF / sepsis / COPD that order D-dimer to screen for
    # complications — their D-dimer rises only via inflammation / DIC. Phase 2a.
    causes_vte: bool = False
    # Primary acid-base disturbance mechanism — routes the scenario's ph_status between the
    # metabolic (HCO3) and respiratory (pCO2) axes so blood gas + compensation are coherent
    # (e.g. DKA = metabolic → Kussmaul low pCO2; COPD = respiratory → compensatory high
    # HCO3). "metabolic" | "respiratory" | "mixed". AD-57.
    acid_base_type: str = "metabolic"
    # Chronic glycemic control implied by the scenario (1.0=excellent .. 0.0=very poor).
    # When set (e.g. DKA/HHS imply long-standing poor control), the inpatient simulator
    # overrides the patient's sampled glycemic_control for this admission so HbA1c is
    # coherently high even for new-onset diabetes (no prior E11 condition). AD-57.
    chronic_glycemic_control: float | None = None
    # Imaging orders (Tier 1 #2 PR1, AD-56): list of imaging studies to place at
    # specified admission days. Optional default = [] so existing disease YAMLs without
    # imaging_orders: remain valid (no-op safe Pydantic optional field).
    imaging_orders: list[ImagingOrderSpec] = Field(default_factory=list)
    # Narrative spec (Tier 1 #3 α-min-1 Task 4): hpi_template, physical_exam_findings,
    # discharge_instructions.  Optional default = None so existing disease YAMLs without
    # a narrative: block continue to validate without error.
    narrative: NarrativeSpec | None = None


@lru_cache(maxsize=64)
def load_disease_protocol(disease_id: str) -> DiseaseProtocol:
    """Load a disease protocol YAML and validate.

    Cached (maxsize=64 covers the ~32 diseases with margin). The returned
    ``DiseaseProtocol`` is a SHARED instance — callers MUST treat it as
    read-only (Pydantic models are mutable by default, but no call site mutates
    the loaded protocol; verified by grep during the loader-commonization
    refactor). Called per scenario in the simulation hot path.
    """
    filename = f"{disease_id}.yaml"
    protocol_path = _REF_DIR / filename
    if not protocol_path.exists():
        raise FileNotFoundError(f"Disease protocol not found: {protocol_path}")

    with open(protocol_path) as f:
        data = yaml.safe_load(f)

    protocol = DiseaseProtocol(**data)
    # Fail-loud severity-block validation (FP-SEV-MODEL). Imported here to avoid a
    # module-import cycle (severity.py has no dependency on protocol.py).
    from clinosim.modules.disease.severity import _validate_severity_block

    _validate_severity_block(disease_id, data.get("severity", {}), protocol.minimum_severity)

    # Fail-loud archetype_modifiers validation (FP-YAML-2b). Effect keys must reference
    # archetypes the disease defines (or the 6 fallback names when it has none).
    from clinosim.modules.clinical_course.engine import (
        _FALLBACK_PROBABILITIES,
        _validate_archetype_modifiers,
    )

    arch_names = set((data.get("course_archetypes") or {}).keys()) or set(_FALLBACK_PROBABILITIES)
    _validate_archetype_modifiers(disease_id, data.get("archetype_modifiers", []), arch_names)

    # Fail-loud course_archetypes[].trajectory state-var validation
    # (FP-DELTA-VALIDATE sibling, session 40). Trajectory keys not in
    # TRAJECTORY_STATE_VARS silently no-op in get_state_changes.
    from clinosim.modules.clinical_course.engine import _validate_course_archetypes

    _validate_course_archetypes(disease_id, data.get("course_archetypes", {}) or {})

    # Fail-loud initial_state_impact + complications state-var validation
    # (FP-DELTA-VALIDATE, session 40). Sibling of anion_gap_status silent-drop
    # closed in session 39 — catches typo'd or unmodeled state-var keys that
    # would silently no-op in apply_state_delta at both delta sinks.
    from clinosim.modules.physiology.engine import (
        _validate_complications_state_impact,
        _validate_initial_state_impact,
    )

    _validate_initial_state_impact(disease_id, data.get("initial_state_impact", {}) or {})
    _validate_complications_state_impact(disease_id, data.get("complications", []) or [])

    # Fail-loud drug-block route fallback validation (Issue #455). Catches entries
    # whose dose string names a route that excludes the fallback the reader would
    # substitute — the class PR #457 missed because its sweep keyed on drug names
    # rather than dose strings.
    _validate_drug_route_consistency(disease_id, data.get("drugs", {}) or {})

    # Fail-loud drug-block duration_days fallback validation (Issue #462).
    # Sibling to the route-fallback check: entries whose dose names an
    # administration interval longer than one week (`weekly`, `q6months` etc.)
    # must declare `duration_days` explicitly, so the reader does not substitute
    # a 7-day supply that contradicts the dose.
    _validate_drug_block_duration_days(disease_id, data.get("drugs", {}) or {})

    # Fail-loud localized dose instruction key typo defense (Issue #476).
    # Catches likely typos of `dose_ja` / `dose_en` (`dose_jp`, `dose_us`, etc.)
    # that would otherwise silently swallow the authored instruction.
    _validate_drug_entry_localized_dose_keys(disease_id, data.get("drugs", {}) or {})

    # Issue #460: drugs.escalation type-signal validation (Layer 1).
    # Layer 2/3 (legacy marker reject + type/route co-occurrence) are wired in a
    # follow-up commit after the 3 shipped YAMLs are migrated (Task 5).
    _validate_escalation_type_signal(disease_id, data.get("drugs", {}) or {})

    # Issue #458: import-time route vocabulary validation. Walks every `route:`
    # value in the whole YAML (not only `drugs`) so newly-added blocks are
    # covered without maintenance here.
    _validate_drug_route_vocabulary(disease_id, data)
    return protocol


@lru_cache(maxsize=1)
def load_all_disease_protocols() -> dict[str, DiseaseProtocol]:
    """Auto-discover and load all disease protocol YAMLs in this package. Cached.

    Globs ``_REF_DIR`` (this module's own ``reference_data/``) in sorted order
    and delegates each file to ``load_disease_protocol``. No silent skip: an
    invalid YAML raises loudly (silent-no-op defense, PR-A lesson). Canonical
    home for the aggregate loader that used to live cross-package in
    ``simulator/helpers.py``.
    """
    protocols: dict[str, DiseaseProtocol] = {}
    for yaml_file in sorted(_REF_DIR.glob("*.yaml")):
        disease_id = yaml_file.stem
        protocols[disease_id] = load_disease_protocol(disease_id)
    return protocols
