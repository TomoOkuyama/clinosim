"""YAML loader for the chronic-medication → monitoring-lab mapping (Issue #757).

Loads `reference_data/medication_monitoring.yaml` into a lookup structure
consumed by `enrich_medication_monitoring`. The loader is intentionally
minimal:

- No caching decorator — the enricher is called once per POST_RECORDS pass
  per run, and the file is small (<10 KB expected for the full pair set).
- Parses into plain dicts (not Pydantic / dataclass) to keep the module's
  external surface small and match the sibling `sdoh.load_social_history`
  loader style.
- Validates schema at load time (fail-loud on missing required keys) so
  a typo in the YAML surfaces immediately rather than as a silent "drug
  never matched" downstream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from clinosim.codes.drugs import drug_display, medication_matches
from clinosim.locale.loaders.demographics import load_code_mapping

_YAML_PATH = Path(__file__).parent / "reference_data" / "medication_monitoring.yaml"


def load_medication_monitoring(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the drug → monitoring-labs mapping.

    Returns a dict keyed by canonical drug name (as declared in YAML) whose
    value is `{"drugs": [...], "classes": [...], "monitoring": [{lab, rationale}, ...]}`.
    Tests can override the file path via the optional `path` argument.

    Raises `ValueError` on schema violations (missing `mappings`, missing
    per-drug `monitoring` list, missing per-lab `lab`, or a `lab` with no
    code in the lab code mapping). No
    silent failure — invalid YAML fails loud at load time rather than
    producing a mysterious "no drugs matched" runtime signature.
    """
    p = path or _YAML_PATH
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    mappings = raw.get("mappings")
    if not isinstance(mappings, dict):
        raise ValueError(f"medication_monitoring.yaml at {p}: missing or non-dict top-level 'mappings' key")
    for drug, entry in mappings.items():
        if not isinstance(entry, dict):
            raise ValueError(f"medication_monitoring.yaml: drug '{drug}' entry must be a dict")
        _validate_drug_selector(f"medication_monitoring.yaml: drug '{drug}'", entry)
        monitoring = entry.get("monitoring")
        if not isinstance(monitoring, list) or not monitoring:
            raise ValueError(f"medication_monitoring.yaml: drug '{drug}' must declare a non-empty 'monitoring' list")
        for i, m in enumerate(monitoring):
            if not isinstance(m, dict):
                raise ValueError(f"medication_monitoring.yaml: drug '{drug}' monitoring[{i}] must be a dict")
            if not m.get("lab"):
                raise ValueError(f"medication_monitoring.yaml: drug '{drug}' monitoring[{i}] missing required 'lab'")
            if not monitoring_lab_code(str(m["lab"])):
                raise ValueError(
                    f"medication_monitoring.yaml: drug '{drug}' monitoring[{i}] lab {m['lab']!r} has no code "
                    "in locale/us/code_mapping_lab.yaml (Issue #2301)"
                )
            interval = m.get("interval_months")
            if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
                raise ValueError(
                    f"medication_monitoring.yaml: drug '{drug}' monitoring[{i}] needs an integer "
                    f"'interval_months' >= 1 (Issue #2143), got {interval!r}"
                )
    return mappings


def monitoring_lab_code(lab: str) -> str:
    """Return the order code for a monitoring lab: its LOINC from the shared lab
    code mapping, the same code its results carry (Issue #2301). Empty when the
    lab is not mapped."""
    return load_code_mapping("lab", "US").get(lab, "")


def matched_medication_names(current_medications: list, mapping: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Map each matched monitoring rule to the (English, Japanese) name of the
    drug the patient actually takes (Issue #2294).

    A rule's class covers other drugs of the class (the Atorvastatin rule
    matches every statin), so order text must name the patient's
    drug, not the rule key. A medication without a Japanese name takes the
    drug catalog's (Issue #2271).
    """
    out: dict[str, tuple[str, str]] = {}
    for drug, entry in mapping.items():
        for med in current_medications or []:
            name = str(getattr(med, "drug_name", None) or (med if isinstance(med, str) else ""))
            if medication_matches(med, entry.get("drugs") or (), entry.get("classes") or ()):
                name_ja = str(getattr(med, "drug_name_ja", "") or "")
                if not name_ja:
                    name_ja = drug_display(name, "ja") or ""
                out[drug] = (name or drug, name_ja or name or drug)
                break
    return out


def match_drugs(current_medications: list, mapping: dict[str, Any]) -> list[str]:
    """Return the list of canonical drug names the patient is on.

    A medication matches a rule by catalog identity: its ``drug_id`` is in
    the rule's ``drugs`` or belongs to one of its ``classes`` (Issue #2371),
    so "Warfarin 3mg PO", "ワルファリン" and "Coumadin" all match the
    Warfarin rule.

    `current_medications` accepts either `HomeMedication` dataclass entries
    (with `.drug_name` attribute) or plain strings (defensive fallback for
    tests / legacy call sites); other shapes are silently skipped.
    """
    matched: list[str] = []
    for drug, entry in mapping.items():
        for med in current_medications or []:
            if medication_matches(med, entry.get("drugs") or (), entry.get("classes") or ()):
                matched.append(drug)
                break
    return matched


def _validate_drug_selector(where: str, entry: dict[str, Any]) -> None:
    """A monitoring rule selects drugs by catalog ``drugs`` ids and / or
    catalog ``classes``; both must exist in the drug catalog (Issue #2371)."""
    from clinosim.codes.drugs import all_drug_ids, drug_classes, get_drug

    drugs, classes = entry.get("drugs") or [], entry.get("classes") or []
    if not isinstance(drugs, list) or not isinstance(classes, list) or not (drugs or classes):
        raise ValueError(f"{where}: needs a non-empty 'drugs' and / or 'classes' list")
    unknown = [d for d in drugs if get_drug(str(d)) is None]
    if unknown:
        raise ValueError(f"{where}: drugs not in the drug catalog: {unknown}")
    known_classes = {c for d in all_drug_ids() for c in drug_classes(d)}
    bad = [c for c in classes if c not in known_classes]
    if bad:
        raise ValueError(f"{where}: classes no catalog drug has: {bad}")
