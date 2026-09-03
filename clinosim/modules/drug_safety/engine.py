"""drug_safety engine — check_pair, check_candidate_against_active, suggest_alternative.

The disease_ctx branch of suggest_alternative is wired in Task 5.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

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
_SHARED_SUBSTITUTION_YAML = _HERE.parents[1] / "locale" / "shared" / "drug_substitution.yaml"


@dataclass(frozen=True)
class AlternativeDrug:
    drug: str
    drug_ja: str
    default_dose: str
    default_route: str
    default_frequency: str
    source_path: str  # yaml provenance, e.g. "locale/shared/drug_substitution.yaml#pain_management[0]"


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
def _load_rules() -> list[dict[str, Any]]:
    with _CONTRAINDICATIONS_YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return list(data.get("rules", []))


def _match_rule(classes_a: list[str], classes_b: list[str]) -> SafetyVerdict:
    """Return the highest-severity SafetyVerdict for (classes_a, classes_b)."""
    set_a = set(classes_a)
    set_b = set(classes_b)
    best: SafetyVerdict = _ALLOWED
    best_rank = -1
    for rule in _load_rules():
        lhs = rule["lhs"]
        rhs = rule["rhs"]
        hit_forward = lhs in set_a and rhs in set_b
        hit_reverse = lhs in set_b and rhs in set_a
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
            rationale_en=rule.get("rationale_en"),
            rationale_ja=rule.get("rationale_ja"),
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
# Alternative substitution
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_shared_substitutions() -> dict[str, dict[str, Any]]:
    with _SHARED_SUBSTITUTION_YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("indications", {}) or {}


def _alt_is_safe(alt_drug: str, active_meds: Sequence[str]) -> bool:
    return not check_candidate_against_active(alt_drug, active_meds)


def _shared_pool_pick(indication: str, active_meds: Sequence[str]) -> AlternativeDrug | None:
    shared = _load_shared_substitutions()
    block = shared.get(indication)
    if not block:
        return None
    for idx, entry in enumerate(block.get("alternatives", []) or []):
        drug = entry.get("drug")
        if not drug or not _alt_is_safe(drug, active_meds):
            continue
        return AlternativeDrug(
            drug=drug,
            drug_ja=entry.get("drug_ja", drug),
            default_dose=entry.get("default_dose", ""),
            default_route=entry.get("default_route", "PO"),
            default_frequency=entry.get("default_frequency", "daily"),
            source_path=(f"locale/shared/drug_substitution.yaml#{indication}[{idx}]"),
        )
    return None


def suggest_alternative(
    candidate: str,
    indication: str | None,
    *,
    active_meds: Sequence[str] = (),
    disease_ctx: Any | None = None,
    country: str = "us",
) -> AlternativeDrug | None:
    """Pick a conflict-free alternative for ``candidate`` given ``indication``.

    Priority order:
      1. disease_ctx alternatives (wired in Task 5) matching ``indication``
      2. locale/shared/drug_substitution.yaml[indication].alternatives
      3. None (fully skipped — caller must handle)

    Every returned alternative has been re-checked via check_pair against
    every entry in ``active_meds`` and is guaranteed conflict-free.
    """
    if indication is None:
        return None

    # Disease-YAML branch — Task 5 wires this to alternatives_by_indication().
    if disease_ctx is not None:
        try:
            from clinosim.modules.disease.protocol import alternatives_by_indication

            disease_alts = alternatives_by_indication(disease_ctx, indication, country)
        except (ImportError, AttributeError):
            disease_alts = []
        for idx, entry in enumerate(disease_alts):
            drug = entry.get("drug")
            if not drug or not _alt_is_safe(drug, active_meds):
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
    return _shared_pool_pick(indication, active_meds)
