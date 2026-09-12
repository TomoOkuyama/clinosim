"""Demographic contraindication gate — pediatric/geriatric/sex-based drug blocks.

Complements the pair-wise ``engine.check_pair`` (drug-drug interaction) with
a "should this drug be prescribed at all given the patient's age/sex?" gate.
Rules load from ``reference_data/demographic_gates.yaml``.

Related Issues:
  - #1276 (pediatric Enoxaparin — first pediatric leak, closed via
    ``prophylaxis.engine`` age gate)
  - #1316 (Tamsulosin to 12 pediatric + 16 female US patients)
  - #1328 (CATASTROPHIC: Aspirin 325 mg + Nitroglycerin to pediatric
    chest-pain path — Reye's syndrome risk, no pediatric NTG indication)
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.modules.drug_safety.verdict import SEVERITY_RANK, Severity

_HERE = Path(__file__).resolve().parent
_DEMOGRAPHIC_GATES_YAML = _HERE / "reference_data" / "demographic_gates.yaml"


@dataclass(frozen=True)
class DemographicVerdict:
    """Result of a demographic gate check.

    ``allowed`` verdicts carry no rule metadata (blocking rules only fill the
    rule_id/severity/rationale fields). Mirror of ``SafetyVerdict`` shape so
    callers can reuse the same skip-logging / substitution path.
    """

    severity: Severity
    rule_id: str | None
    matched_drug_name: str | None
    rationale_en: str | None
    rationale_ja: str | None

    @property
    def is_allowed(self) -> bool:
        return self.severity == "allowed"

    @property
    def should_skip(self) -> bool:
        return SEVERITY_RANK[self.severity] >= SEVERITY_RANK["major"]


_ALLOWED = DemographicVerdict(
    severity="allowed",
    rule_id=None,
    matched_drug_name=None,
    rationale_en=None,
    rationale_ja=None,
)


@lru_cache(maxsize=1)
def _load_rules() -> list[dict[str, Any]]:
    with _DEMOGRAPHIC_GATES_YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    rules = list(data.get("rules", []) or [])
    for r in rules:
        if not r.get("id"):
            raise ValueError(f"demographic_gates.yaml: rule missing id: {r!r}")
        if not r.get("drug_names"):
            raise ValueError(f"demographic_gates.yaml: rule {r['id']} missing drug_names")
        if r.get("severity") not in SEVERITY_RANK:
            raise ValueError(
                f"demographic_gates.yaml: rule {r['id']} severity {r.get('severity')!r} not in {sorted(SEVERITY_RANK)}"
            )
    return rules


def _drug_matches(candidate: str, drug_names: list[str]) -> str | None:
    """Case-insensitive substring match. Returns the matched alias or None.

    Longest alias first so "Tamsulosin XR" prefers "Tamsulosin" over any
    shorter spurious substring. Mirrors ``classifier._build_alias_index``.
    """
    if not candidate:
        return None
    lc = candidate.lower()
    for alias in sorted(drug_names, key=lambda a: -len(str(a))):
        if str(alias).strip().lower() in lc:
            return str(alias)
    return None


def _normalize_sex(sex: str | None) -> str | None:
    if not sex:
        return None
    s = sex.strip().lower()
    if s in ("m", "male"):
        return "male"
    if s in ("f", "female"):
        return "female"
    return s or None


def _indication_matches(
    exception_prefixes: list[str] | None,
    indication_codes: list[str] | None,
) -> bool:
    if not exception_prefixes or not indication_codes:
        return False
    for code in indication_codes:
        if not code:
            continue
        for pfx in exception_prefixes:
            if str(code).startswith(str(pfx)):
                return True
    return False


def check_demographic_gate(
    drug_name: str,
    *,
    patient_age: int | None,
    patient_sex: str | None,
    indication_codes: list[str] | None = None,
) -> DemographicVerdict:
    """Return the highest-severity demographic verdict for the candidate drug.

    Args:
        drug_name: order display text (may include dose, e.g. "Aspirin 325mg").
        patient_age: integer years at the ordering timestamp; ``None`` skips age gates.
        patient_sex: "M"/"F" / "male"/"female" / other locale text; ``None``
            skips sex gates.
        indication_codes: ICD-10 codes attached to the ordering encounter
            (or the patient's active problem list). Any prefix-match against
            a rule's ``exception_indications`` bypasses that rule.

    Returns an ``_ALLOWED`` verdict when no rule fires. When multiple rules
    fire, the highest-severity verdict is returned (ties: first rule wins).
    """
    normalized_sex = _normalize_sex(patient_sex)
    best = _ALLOWED
    best_rank = -1
    for rule in _load_rules():
        matched = _drug_matches(drug_name, rule["drug_names"])
        if matched is None:
            continue
        # Age gates
        min_age = rule.get("min_age")
        max_age = rule.get("max_age")
        age_fail = False
        if min_age is not None and patient_age is not None and patient_age < int(min_age):
            age_fail = True
        if max_age is not None and patient_age is not None and patient_age > int(max_age):
            age_fail = True
        # Sex gate
        rule_sex = rule.get("sex")
        sex_fail = (
            rule_sex is not None and normalized_sex is not None and _normalize_sex(str(rule_sex)) != normalized_sex
        )
        if not (age_fail or sex_fail):
            continue
        # Exception indication bypass
        if _indication_matches(rule.get("exception_indications"), indication_codes):
            continue
        severity: Severity = rule["severity"]
        rank = SEVERITY_RANK[severity]
        if rank <= best_rank:
            continue
        best = DemographicVerdict(
            severity=severity,
            rule_id=rule["id"],
            matched_drug_name=matched,
            rationale_en=rule.get("rationale_en"),
            rationale_ja=rule.get("rationale_ja"),
        )
        best_rank = rank
    return best
