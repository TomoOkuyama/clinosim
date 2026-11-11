"""drug_safety engine — check_pair, check_candidate_against_active, suggest_alternative.

The disease_ctx branch of suggest_alternative reads disease-YAML
alternatives via ``disease.protocol.alternatives_by_indication``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from clinosim.datafiles import load_validated_yaml
from clinosim.locale.localized import language_slot
from clinosim.modules.drug_safety._models import (
    AllergyContraindicationsFile,
    ContraindicationsFile,
    DiseaseContraindicationsFile,
    DrugSubstitutionFile,
)
from clinosim.modules.drug_safety.classifier import (
    canonical_name,
    japanese_display,
    resolve_classes,
)
from clinosim.modules.drug_safety.verdict import (
    SEVERITY_RANK,
    SafetyVerdict,
    Severity,
)

_HERE = Path(__file__).resolve().parent
_CONTRAINDICATIONS_YAML = _HERE / "reference_data" / "contraindications.yaml"
_DISEASE_CONTRAINDICATIONS_YAML = _HERE / "reference_data" / "disease_contraindications.yaml"
_SHARED_SUBSTITUTION_YAML = _HERE / "reference_data" / "drug_substitution.yaml"
_ALLERGY_CONTRAINDICATIONS_YAML = _HERE / "reference_data" / "allergy_contraindications.yaml"


@dataclass(frozen=True)
class AlternativeDrug:
    drug: str
    drug_ja: str
    default_dose: str
    default_route: str
    default_frequency: str
    # yaml provenance, e.g. "modules/drug_safety/reference_data/drug_substitution.yaml#pain_management[0]"
    source_path: str


_ALLOWED = SafetyVerdict(
    severity="allowed",
    rule_id=None,
    matched_classes=None,
    matched_active_drug=None,
    rationale_en=None,
    rationale_ja=None,
    substitution_hint=None,
)


@lru_cache(maxsize=1)
def _contraindications_file() -> dict[str, Any]:
    """``contraindications.yaml``, validated by ``ContraindicationsFile``."""
    return load_validated_yaml(_CONTRAINDICATIONS_YAML, ContraindicationsFile)


@lru_cache(maxsize=1)
def discharge_reconciliation_rules() -> frozenset[str]:
    """Rule ids the discharge prescription reconciles (Issue #2713)."""
    return frozenset(str(r) for r in _contraindications_file().get("discharge_reconciliation_rules") or [])


def triple_therapy_after_acs_plan() -> dict[str, Any]:
    """The antithrombotic plan for a patient on an anticoagulant who leaves on
    DAPT after ACS (``contraindications.yaml`` ``triple_therapy_after_acs``)."""
    return dict(_contraindications_file()["triple_therapy_after_acs"])


@lru_cache(maxsize=1)
def _load_rules() -> list[dict[str, Any]]:
    return list(_contraindications_file().get("rules", []))


def _exempt(rule: dict[str, Any], lhs_side: set[str], rhs_side: set[str]) -> bool:
    """True when the drug pair is one the rule's ``exempt`` list excludes
    (Issue #3003: heparin with antiplatelet aspirin)."""
    return any(ex["lhs"] in lhs_side and ex["rhs"] in rhs_side for ex in rule.get("exempt") or ())


def _match_rule(classes_a: list[str], classes_b: list[str]) -> SafetyVerdict:
    """Return the highest-severity SafetyVerdict for (classes_a, classes_b)."""
    set_a = set(classes_a)
    set_b = set(classes_b)
    best: SafetyVerdict = _ALLOWED
    best_rank = -1
    for rule in _load_rules():
        lhs = rule["lhs"]
        rhs = rule["rhs"]
        hit_forward = lhs in set_a and rhs in set_b and not _exempt(rule, set_a, set_b)
        hit_reverse = lhs in set_b and rhs in set_a and not _exempt(rule, set_b, set_a)
        if not (hit_forward or hit_reverse):
            continue
        severity: Severity = rule["severity"]
        rank = SEVERITY_RANK[severity]
        if rank <= best_rank:
            continue
        matched = (lhs, rhs) if hit_forward else (rhs, lhs)
        best = SafetyVerdict(
            severity=severity,
            rule_id=rule["id"],
            matched_classes=matched,
            matched_active_drug=None,
            rationale_en=language_slot(rule.get("rationale"), "en") or None,
            rationale_ja=language_slot(rule.get("rationale"), "ja") or None,
            substitution_hint=rule.get("substitution_hint"),
        )
        best_rank = rank
    return best


def check_pair(drug_a: str, drug_b: str) -> SafetyVerdict:
    classes_a = resolve_classes(drug_a)
    classes_b = resolve_classes(drug_b)
    if not classes_a or not classes_b:
        return _ALLOWED
    return _match_rule(classes_a, classes_b)


def check_candidate_against_active(
    candidate: str,
    active_meds: Sequence[str],
) -> list[SafetyVerdict]:
    """Return list of non-allowed verdicts (empty = safe to add).

    Each verdict carries ``matched_active_drug`` populated with the canonical
    name of the active med that triggered it.
    """
    out: list[SafetyVerdict] = []
    for active in active_meds:
        v = check_pair(candidate, active)
        if v.is_allowed:
            continue
        active_canonical = canonical_name(active) or active
        out.append(
            SafetyVerdict(
                severity=v.severity,
                rule_id=v.rule_id,
                matched_classes=v.matched_classes,
                matched_active_drug=active_canonical,
                rationale_en=v.rationale_en,
                rationale_ja=v.rationale_ja,
                substitution_hint=v.substitution_hint,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Disease-state contraindication check (Issue #1392 Cluster A — #1350 / #1335)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_disease_rules() -> list[dict[str, Any]]:
    """Load disease-vs-drug-class rules from ``disease_contraindications.yaml``.

    Cached — the YAML never changes at runtime; a test that needs to
    reload should clear this cache directly."""
    data = load_validated_yaml(_DISEASE_CONTRAINDICATIONS_YAML, DiseaseContraindicationsFile)
    return list(data.get("rules", []))


def _condition_matches_predicate(condition_entry: Any, predicate: dict[str, Any]) -> bool:
    """Match one condition entry against a ``disease_predicate`` block.

    ``condition_entry`` is either a bare ICD code string (``"I50.32"``,
    the pre-#1769 shape) or a ``(code, stage)`` tuple carrying the
    chronic condition's staged severity (``("N18", "CKD G3b")``). The
    predicate supports:

    * ``icd_prefix`` (list of strings) — ANY entry's ``code`` begins
      with ANY listed prefix. Required.
    * ``stage_in`` (list of strings, Issue #1769) — when present, the
      entry MUST carry a stage AND the stage MUST appear in the list.
      A bare-string entry (no stage) FAILS the predicate — fail-closed
      is correct: a caller that lost stage context should not get a
      stage-contingent rule to fire by accident.

    Rules without ``stage_in`` keep the pre-#1769 code-only semantics
    for both bare-string and tuple entries (tuple entry falls through
    to code match). Extend here for future predicate kinds
    (``sex``, ``age_min``, chronic-condition flags, etc.).
    """
    prefixes = predicate.get("icd_prefix") or []
    if isinstance(condition_entry, tuple):
        code = condition_entry[0] if condition_entry else ""
        stage = condition_entry[1] if len(condition_entry) >= 2 else ""
    else:
        code = condition_entry or ""
        stage = ""
    if not code:
        return False
    if not any(str(code).startswith(str(p)) for p in prefixes):
        return False
    stage_in = predicate.get("stage_in")
    if stage_in:
        return bool(stage) and str(stage) in {str(s) for s in stage_in}
    return True


def condition_entries(conditions: Sequence[Any]) -> list[tuple[str, str]]:
    """``(code, stage)`` entries of chronic conditions for
    :func:`check_candidate_against_disease_state` — the code as stored
    (base form such as ``N18``) and the staged severity (``"CKD G4"``) or
    ``""``. Conditions without a code are left out."""
    return [
        (str(cond.code), str(getattr(cond, "stage", "") or "")) for cond in conditions if getattr(cond, "code", None)
    ]


def check_candidate_against_disease_state(
    candidate: str,
    active_conditions: Sequence[Any],
) -> list[SafetyVerdict]:
    """Return the list of non-allowed drug-vs-disease-state verdicts.

    ``candidate`` is a drug name (canonical or alias). Its expanded
    class list (``resolve_classes``) is intersected against each rule's
    ``drug_class`` filter; matching rules then check whether any
    ``active_conditions`` entry meets the rule's ``disease_predicate``.
    Every triggered rule appears as a :class:`SafetyVerdict` in the
    returned list — callers pick the highest-severity entry to drive
    skip / warn.

    Each entry in ``active_conditions`` is either a bare ICD code
    (``"I50"``, ``"N18.4"``) OR a ``(code, stage)`` tuple carrying the
    patient's staged chronic severity. Rules with a ``stage_in``
    predicate (Issue #1769) only fire when a tuple entry's stage falls
    in the listed set; rules without ``stage_in`` keep the pre-#1769
    code-prefix semantics for both shapes.

    Empty return value = no drug-vs-disease-state rule triggered; the
    candidate may still hit a drug-vs-drug rule via
    :func:`check_candidate_against_active`.

    Kept as a peer function of ``check_candidate_against_active`` — a
    caller normally invokes both and combines verdicts.
    """
    classes = resolve_classes(candidate)
    if not classes:
        return []
    class_set = set(classes)
    out: list[SafetyVerdict] = []
    for rule in _load_disease_rules():
        rule_class = str(rule.get("drug_class") or "")
        if rule_class and rule_class not in class_set:
            continue
        predicate = rule.get("disease_predicate") or {}
        matched_entry = next(
            (entry for entry in active_conditions if _condition_matches_predicate(entry, predicate)),
            None,
        )
        if matched_entry is None:
            continue
        # Record the code portion for backward-compat parity with the
        # pre-#1769 ``matched_classes`` tuple format (callers see the
        # ICD code, not the stage).
        matched_code = matched_entry[0] if isinstance(matched_entry, tuple) else matched_entry
        severity: Severity = rule.get("severity", "moderate")
        out.append(
            SafetyVerdict(
                severity=severity,
                rule_id=rule.get("id"),
                matched_classes=(rule_class, str(matched_code)),
                matched_active_drug=None,
                rationale_en=language_slot(rule.get("rationale"), "en") or None,
                rationale_ja=language_slot(rule.get("rationale"), "ja") or None,
                substitution_hint=rule.get("substitution_hint"),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Recorded-allergy check (Issue #2924)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_allergy_rules() -> list[dict[str, Any]]:
    """Drug-class × allergen rules of ``allergy_contraindications.yaml``."""
    data = load_validated_yaml(_ALLERGY_CONTRAINDICATIONS_YAML, AllergyContraindicationsFile)
    return list(data.get("rules", []))


@lru_cache(maxsize=1)
def _allergy_rule_ids() -> frozenset[str]:
    return frozenset(str(r["id"]) for r in _load_allergy_rules())


def rule_kind(rule_id: str | None) -> str | None:
    """What kind of rule ``rule_id`` (a ``SafetyVerdict.rule_id``) is:
    ``"allergy"`` (drug x recorded allergy), ``"disease"`` (drug x disease
    state), ``"interaction"`` (drug x drug), or None for any other id (a
    protocol hold, a demographic gate, ...). Issue #2930: the narrative words
    an allergy skip as an allergy, not as a co-administration conflict."""
    if not rule_id:
        return None
    if rule_id in _allergy_rule_ids():
        return "allergy"
    if rule_id in _disease_rule_ids():
        return "disease"
    if rule_id in _pair_rule_ids():
        return "interaction"
    return None


@lru_cache(maxsize=1)
def _disease_rule_ids() -> frozenset[str]:
    return frozenset(str(r["id"]) for r in _load_disease_rules() if r.get("id"))


@lru_cache(maxsize=1)
def _pair_rule_ids() -> frozenset[str]:
    return frozenset(str(r["id"]) for r in _load_rules() if r.get("id"))


def allergy_entries(allergies: Sequence[Any]) -> list[str]:
    """Allergen codes of the patient's active allergy records for
    :func:`check_candidate_against_allergies`: clinical status ``active``,
    not refuted, not the "No known allergy" assertion."""
    out: list[str] = []
    for allergy in allergies or ():
        if getattr(allergy, "is_nka", False):
            continue
        if str(getattr(allergy, "clinical_status", "active") or "active") != "active":
            continue
        if str(getattr(allergy, "verification_status", "") or "") in {"refuted", "entered-in-error"}:
            continue
        code = str(getattr(allergy, "allergen_code", "") or "")
        if code and code not in out:
            out.append(code)
    return out


def check_candidate_against_allergies(candidate: str, allergen_codes: Sequence[str]) -> list[SafetyVerdict]:
    """Non-allowed verdicts of ``candidate`` against the patient's active
    allergen codes (:func:`allergy_entries`). A rule fires when its
    ``allergen_code`` is recorded and the candidate belongs to one of its
    ``drug_classes`` and to none of its ``exclude_classes``.
    ``matched_classes`` is ``(drug class, allergen code)``."""
    if not allergen_codes:
        return []
    classes = set(resolve_classes(candidate))
    if not classes:
        return []
    codes = set(allergen_codes)
    out: list[SafetyVerdict] = []
    for rule in _load_allergy_rules():
        if str(rule["allergen_code"]) not in codes:
            continue
        if classes & set(rule.get("exclude_classes") or ()):
            continue
        matched = next((c for c in rule["drug_classes"] if c in classes), None)
        if matched is None:
            continue
        severity: Severity = rule["severity"]
        out.append(
            SafetyVerdict(
                severity=severity,
                rule_id=rule["id"],
                matched_classes=(str(matched), str(rule["allergen_code"])),
                matched_active_drug=None,
                rationale_en=language_slot(rule.get("rationale"), "en") or None,
                rationale_ja=language_slot(rule.get("rationale"), "ja") or None,
                substitution_hint=rule.get("substitution_hint"),
            )
        )
    return out


def conflict_display(verdict: SafetyVerdict) -> tuple[str, str]:
    """(English, Japanese) text of what ``verdict`` conflicts with, for a
    ``SafetySkipEntry``: the recorded allergy of an allergy rule ("Penicillin
    allergy"), otherwise the active drug that triggered it."""
    if verdict.rule_id in _allergy_rule_ids() and verdict.matched_classes:
        from clinosim.codes import lookup
        from clinosim.locale.i18n import t

        code = verdict.matched_classes[1]
        en = t("safety_text.allergy_conflict", "en", allergen=lookup("snomed-ct", code, "en"))
        ja = t("safety_text.allergy_conflict", "ja", allergen=lookup("snomed-ct", code, "ja"))
        return en, ja
    active = verdict.matched_active_drug or ""
    return active, (japanese_display(active) or active)


def allergy_skip_verdict(candidate: str, allergies: Sequence[Any]) -> SafetyVerdict | None:
    """The highest-severity allergy verdict that drops ``candidate`` for a
    patient with ``allergies`` (allergy records), or None when it may be
    given (a caution-level verdict does not drop it)."""
    verdicts = check_candidate_against_allergies(candidate, allergy_entries(allergies))
    worst = max(verdicts, key=lambda v: SEVERITY_RANK[v.severity], default=None)
    return worst if worst is not None and worst.default_action == "skip" else None


# ---------------------------------------------------------------------------
# Alternative substitution
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_shared_substitutions() -> dict[str, dict[str, Any]]:
    data = load_validated_yaml(_SHARED_SUBSTITUTION_YAML, DrugSubstitutionFile)
    return data.get("indications", {}) or {}


def _alt_is_safe(alt_drug: str, active_meds: Sequence[str], allergen_codes: Sequence[str] = ()) -> bool:
    if check_candidate_against_active(alt_drug, active_meds):
        return False
    # Issue #2924: an alternative the patient is allergic to is no alternative.
    return not any(v.default_action == "skip" for v in check_candidate_against_allergies(alt_drug, allergen_codes))


def _resolve_substitution_display(entry: dict[str, Any]) -> tuple[str, str]:
    """Resolve (en, ja) display for a drug_substitution.yaml alternative.

    META #1804 Phase 2.b: prefer the catalog's resolve_drug when the
    entry carries ``drug_id``; fall back to the legacy ``drug`` /
    ``drug_ja`` fields for entries not yet migrated. The catalog is
    the display SoT once a drug_id is set.
    """
    drug_id = str(entry.get("drug_id") or "")
    if drug_id:
        from clinosim.codes.drugs import resolve_drug

        rec = resolve_drug(drug_id)
        en = rec.names.get("en", "") or ""
        ja = rec.names.get("ja", "") or en
        return en, ja
    from clinosim.codes.drugs import drug_display

    legacy_en = str(entry.get("drug", "") or "")
    return legacy_en, drug_display(legacy_en, "ja") or legacy_en


def _shared_pool_pick(
    indication: str, active_meds: Sequence[str], allergen_codes: Sequence[str] = ()
) -> AlternativeDrug | None:
    shared = _load_shared_substitutions()
    block = shared.get(indication)
    if not block:
        return None
    for idx, entry in enumerate(block.get("alternatives", []) or []):
        drug_en, drug_ja = _resolve_substitution_display(entry)
        if not drug_en or not _alt_is_safe(drug_en, active_meds, allergen_codes):
            continue
        return AlternativeDrug(
            drug=drug_en,
            drug_ja=drug_ja,
            default_dose=entry.get("default_dose", ""),
            default_route=entry.get("default_route", "PO"),
            default_frequency=entry.get("default_frequency", "daily"),
            source_path=(f"modules/drug_safety/reference_data/drug_substitution.yaml#{indication}[{idx}]"),
        )
    return None


def _alternative_name(entry: dict[str, Any]) -> str:
    """English catalog name of a disease-YAML alternative (``drug_id``, else
    the legacy ``drug`` name); ``""`` when neither resolves (Issue #2497)."""
    drug_id = str(entry.get("drug_id") or "")
    if drug_id:
        from clinosim.codes.drugs import drug_display

        return drug_display(drug_id, "en") or ""
    return str(entry.get("drug") or "")


def suggest_alternative(
    candidate: str,
    indication: str | None,
    *,
    active_meds: Sequence[str] = (),
    disease_ctx: Any | None = None,
    country: str,
    allergen_codes: Sequence[str] = (),
) -> AlternativeDrug | None:
    """Pick a conflict-free alternative for ``candidate`` given ``indication``.

    Priority order:
      1. disease_ctx alternatives (``alternatives_by_indication``) matching ``indication``
      2. modules/drug_safety/reference_data/drug_substitution.yaml[indication].alternatives
      3. None (fully skipped — caller must handle)

    Every returned alternative has been re-checked via check_pair against
    every entry in ``active_meds`` and is guaranteed conflict-free; it is
    also not one the patient's ``allergen_codes`` (:func:`allergy_entries`)
    rule out (Issue #2924).
    """
    if indication is None:
        return None

    # Disease-YAML branch — alternatives_by_indication() on the disease protocol.
    if disease_ctx is not None:
        try:
            from clinosim.modules.disease.protocol import alternatives_by_indication

            disease_alts = alternatives_by_indication(disease_ctx, indication, country)
        except (ImportError, AttributeError):
            disease_alts = []
        for idx, entry in enumerate(disease_alts):
            # Disease YAMLs name the alternative by catalog `drug_id`
            # (protocol drugs are catalog ids); `drug` is the legacy name key.
            drug = _alternative_name(entry)
            if not drug or not _alt_is_safe(drug, active_meds, allergen_codes):
                continue
            disease_id = getattr(disease_ctx, "disease_id", "unknown")
            return AlternativeDrug(
                drug=drug,
                drug_ja=japanese_display(drug) or drug,
                default_dose=entry.get("dose", ""),
                default_route="PO",  # disease YAML dose strings encode route inline
                default_frequency="daily",
                source_path=(f"clinosim/modules/disease/reference_data/{disease_id}.yaml#{indication}[{idx}]"),
            )

    # Shared-pool fallback
    return _shared_pool_pick(indication, active_meds, allergen_codes)
