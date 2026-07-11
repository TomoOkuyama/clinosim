"""Session 45 regression guard: disease YAML drug name ↔ code_yj/code_rxnorm
consistency vs canonical code_mapping_drug.yaml.

Original finding (2026-07-11): pulmonary_embolism.yaml + 3 sibling YAMLs
declared `drug: "Unfractionated Heparin", code_yj: "3334400"`, where 3334400
maps to Enoxaparin (not Heparin). The Heparin YJ code is 3334002. The
production JP p=10000 cohort therefore emitted 548+ Enoxaparin `coding` under
"未分画ヘパリン" text — a silent-code-substitution defect.

This test scans every disease YAML for drug blocks of shape::

    - drug: "<name>"
      code_(yj|rxnorm): "<code>"

and asserts that <code>'s canonical name in the country-specific
code_mapping_drug.yaml matches <name> (after stripping qualifier prefixes:
"Unfractionated", "Regular", "Recombinant", "Human", "Low molecular weight").

Known aliases are enumerated in _ALLOWED_ALIASES below — these are drug-name
synonyms that legitimately share a code (Albuterol/Salbutamol INN pair,
Insulin_regular/Sliding scale insulin protocol/formulation pair).
Unknown codes (not present in code_mapping) are skipped — they may be
legitimate new drugs not yet added to code_mapping.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_DISEASES = _ROOT / "clinosim/modules/disease/reference_data"
_JP_MAP = yaml.safe_load(
    (_ROOT / "clinosim/locale/jp/code_mapping_drug.yaml").read_text()
)
_US_MAP = yaml.safe_load(
    (_ROOT / "clinosim/locale/us/code_mapping_drug.yaml").read_text()
)

_JP_CODE_TO_NAME: dict[str, str] = {}
for _name, _code in _JP_MAP.items():
    _JP_CODE_TO_NAME.setdefault(_code, _name)
_US_CODE_TO_NAME: dict[str, str] = {}
for _name, _code in _US_MAP.items():
    _US_CODE_TO_NAME.setdefault(_code, _name)

# Legitimate drug-name aliases (same molecule / same protocol, different name).
# Key = normalized disease-YAML drug name, value = set of accepted canonical
# names from code_mapping_drug.yaml. Any pair present here is NOT flagged.
_ALLOWED_ALIASES: dict[str, set[str]] = {
    "albuterol": {"salbutamol"},
    "salbutamol": {"albuterol"},
    "insulin regular": {"sliding scale insulin"},
    "regular insulin": {"sliding scale insulin"},
    "sliding scale insulin": {"insulin regular", "regular insulin"},
}

# Known-broken US code_rxnorm mismatches (session 45 sibling-sweep finding).
# rxnorm.yaml carries no entry for these codes so US emit resolves to
# unmapped display anyway. Tracked in TODO.md session-45-drug-code-audit for
# authoritative RxNav lookup + fix in a follow-up chain.
_KNOWN_MISMATCHES_TODO: set[tuple[str, str, str, str]] = {
    ("acute_pancreatitis.yaml", "Hydromorphone", "rxnorm", "3423"),
    ("aspiration_pneumonia.yaml", "Moxifloxacin", "rxnorm", "139462"),
    ("hemorrhagic_stroke.yaml", "Vitamin K", "rxnorm", "11253"),
    ("hemorrhagic_stroke.yaml", "4-Factor PCC (Kcentra)", "rxnorm", "1364430"),
    ("sepsis.yaml", "Aztreonam", "rxnorm", "18631"),
}

_QUALIFIER_PREFIXES = (
    "unfractionated",
    "regular",
    "recombinant",
    "human",
    "low molecular weight",
)


def _norm(name: str) -> str:
    n = name.strip().lower().replace("_", " ")
    changed = True
    while changed:
        changed = False
        for pfx in _QUALIFIER_PREFIXES:
            if n.startswith(pfx + " "):
                n = n[len(pfx) + 1 :]
                changed = True
                break
    return n


_DRUG_BLOCK_RE = re.compile(
    r'- drug:\s*"([^"]+)"\s*\n'
    r"(?:\s+[a-z_]+:\s*.+\n){0,3}?"
    r'\s+code_(yj|rxnorm):\s*"([^"]+)"'
)


@pytest.mark.unit
def test_disease_yaml_drug_code_consistency():
    """Every disease YAML drug + code_(yj|rxnorm) must map to the same drug in
    code_mapping_drug.yaml (or be a documented alias / TODO)."""
    real_mismatches: list[str] = []
    for f in sorted(_DISEASES.glob("*.yaml")):
        text = f.read_text()
        for m in _DRUG_BLOCK_RE.finditer(text):
            drug_name = m.group(1)
            code_type = m.group(2)
            code_val = m.group(3)
            canonical = (
                _JP_CODE_TO_NAME.get(code_val)
                if code_type == "yj"
                else _US_CODE_TO_NAME.get(code_val)
            )
            if not canonical:
                continue  # unknown code — no ground truth
            drug_norm = _norm(drug_name)
            canonical_norm = _norm(canonical)
            if drug_norm == canonical_norm:
                continue
            if canonical_norm in _ALLOWED_ALIASES.get(drug_norm, set()):
                continue
            if (f.name, drug_name, code_type, code_val) in _KNOWN_MISMATCHES_TODO:
                continue
            real_mismatches.append(
                f"{f.name}: drug={drug_name!r} code_{code_type}={code_val} "
                f"but code_mapping says {canonical!r}"
            )
    assert not real_mismatches, (
        "Disease YAML drug/code mismatch(es):\n" + "\n".join(real_mismatches)
    )
