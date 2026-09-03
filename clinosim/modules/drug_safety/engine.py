"""drug_safety engine — check_pair, check_candidate_against_active.

``suggest_alternative`` is added in Task 4 (shared pool path) and Task 5
(disease_ctx branch).
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.modules.drug_safety.classifier import (
    canonical_name,
    resolve_classes,
)
from clinosim.modules.drug_safety.verdict import (
    SEVERITY_RANK,
    SafetyVerdict,
    Severity,
)

_HERE = Path(__file__).resolve().parent
_CONTRAINDICATIONS_YAML = _HERE / "reference_data" / "contraindications.yaml"

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
