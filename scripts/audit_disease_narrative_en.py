#!/usr/bin/env python3
"""Audit (AD-65 Bug A, Task 10): every narrative.* lang-suffixed field must
have both an `_en` and a `_ja` variant.

Covers two YAML sets that carry `<key>_<lang>` narrative fields:

1. Disease YAMLs (`clinosim/modules/disease/reference_data/*.yaml`) —
   `narrative.<key>_en` / `narrative.<key>_ja` for
   hpi / physical_examination / assessment_and_plan / chief_complaint.
   NOTE: as of Task 10, none of the 32 disease YAMLs actually use this
   suffix convention for these four keys — `chief_complaint` uses a plain
   `{en: ..., ja: ...}` dict (already fully bilingual, see
   test_diagnosis_code_coverage.py) and `hpi_template.onset_pattern` /
   `physical_exam_findings` carry no per-language split at all (a separate,
   deferred structured-object data-authoring gap — see Task 9 report and
   template_generator.py module docstring). This scan is retained per the
   original brief so any future disease YAML that DOES adopt the suffix
   convention is still covered.

2. Encounter YAMLs (`clinosim/modules/encounter/reference_data/*.yaml`) —
   `narrative.ed_note_template.<key>_en/_ja` for
   chief_complaint / hpi / physical_exam / ed_workup_summary / disposition,
   and `narrative.outpatient_soap_template.<key>_en/_ja` for
   subjective / objective / assessment / plan. This is where the actual
   Bug A gap lives (Task 9 investigation): every encounter YAML has `_ja`
   fields but zero have `_en` peers.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[1]
DISEASE_DIR = _ROOT / "clinosim/modules/disease/reference_data"
ENCOUNTER_DIR = _ROOT / "clinosim/modules/encounter/reference_data"

DISEASE_NARRATIVE_KEYS = ("hpi", "physical_examination", "assessment_and_plan", "chief_complaint")

ED_NOTE_KEYS = ("chief_complaint", "hpi", "physical_exam", "ed_workup_summary", "disposition")
OUTPATIENT_SOAP_KEYS = ("subjective", "objective", "assessment", "plan")


def _check_keys(container: dict[str, Any], keys: tuple[str, ...], label: str) -> list[str]:
    missing: list[str] = []
    for key in keys:
        has_en = f"{key}_en" in container
        has_ja = f"{key}_ja" in container
        if has_ja and not has_en:
            missing.append(f"{label}: {key}_en missing (ja present)")
        if has_en and not has_ja:
            missing.append(f"{label}: {key}_ja missing (en present)")
    return missing


def check_disease(path: Path) -> list[str]:
    doc = yaml.safe_load(path.read_text())
    narrative = (doc or {}).get("narrative", {}) or {}
    if not narrative:
        return []
    return _check_keys(narrative, DISEASE_NARRATIVE_KEYS, path.name)


def check_encounter(path: Path) -> list[str]:
    doc = yaml.safe_load(path.read_text())
    narrative = (doc or {}).get("narrative", {}) or {}
    if not narrative:
        return []

    missing: list[str] = []

    ed_tmpl = narrative.get("ed_note_template")
    if isinstance(ed_tmpl, dict):
        missing.extend(_check_keys(ed_tmpl, ED_NOTE_KEYS, f"{path.name} [ed_note_template]"))

    soap_tmpl = narrative.get("outpatient_soap_template")
    if isinstance(soap_tmpl, dict):
        missing.extend(
            _check_keys(soap_tmpl, OUTPATIENT_SOAP_KEYS, f"{path.name} [outpatient_soap_template]")
        )

    return missing


def main() -> int:
    all_missing: list[str] = []
    for path in sorted(DISEASE_DIR.glob("*.yaml")):
        all_missing.extend(check_disease(path))
    for path in sorted(ENCOUNTER_DIR.glob("*.yaml")):
        all_missing.extend(check_encounter(path))

    if all_missing:
        print("Missing narrative en/ja fields:")
        for m in all_missing:
            print(f"  {m}")
        print(f"\nTotal: {len(all_missing)}")
        return 1

    print("OK: all disease + encounter YAMLs have narrative _en/_ja variants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
