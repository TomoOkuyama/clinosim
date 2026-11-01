"""Localized values are selected through ``clinosim.locale.localized``: no
direct ``.get("ja")`` and no ``x_ja if is_jp(...)`` selection elsewhere
(Issue #2397). The allowlist names the lines that do not select a value for
output, with the reason."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import clinosim

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_PATTERN = re.compile(r'\.get\("ja"\)|_ja(\(\))? if is_jp\(')

# (file, code fragment) → why it is not a language selection.
_ALLOWED = {
    ("codes/drugs.py", 'if not names.get("ja"):'): "catalog validation: names.ja is required",
    ("locale/loaders/narrative.py", 'ja = (rec.names.get("ja") or "").strip()'): "builds the JA display dictionary",
    ("locale/loaders/narrative.py", 'ja_val = str((entry or {}).get("ja") or "")'): "builds the JA display dictionary",
    (
        "simulator/perinatal.py",
        'ja_reason = (ab_cfg.get("visit_reason") or {}).get("ja") or ""',
    ): "fills the record's _ja field",
    ("simulator/perinatal.py", 'ja_reason = _reason_cfg.get("ja") or ""'): "fills the record's _ja field",
    ("modules/output/fhir_r4/medications/medications.py", 'ja = tuple(str(m) for m in (row.get("ja") or [])'): (
        "collects JA match patterns of a table row"
    ),
    (
        "modules/document/narrative/renderers/section_builders/outpatient_soap.py",
        'ja = tuple(str(h) for h in (row.get("ja") or [])',
    ): ("collects JA match patterns of a table row"),
    (
        "modules/document/narrative/_template_helpers.py",
        '"chief_complaint_ja": str(cc.get("ja") or "")',
    ): "fills the _ja field",
    (
        "modules/document/narrative/_replacement_localization.py",
        'en, ja = str(entry.get("en") or ""), str(entry.get("ja") or "")',
    ): ("builds an EN→JA replacement pair"),
    (
        "modules/document/narrative/renderers/_resolvers.py",
        'sec_data.get("en") or sec_data.get("ja")',
    ): "presence check",
    (
        "modules/immunization/enricher.py",
        'chief_complaint_ja=chief_ja if is_jp(country) else ""',
    ): "fills the _ja field only for JP",
    ("modules/output/fhir_r4/documents/composition.py", "suffix_map = _staff_role_suffix_ja() if is_jp(country)"): (
        "selects a literal table; moves to a catalog with the FHIR literals (#2404)"
    ),
}


def test_no_direct_language_selection() -> None:
    offenders = []
    for path in _ROOT.rglob("*.py"):
        rel = path.relative_to(_ROOT).as_posix()
        if rel == "locale/localized.py":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#", 1)[0]
            if not _PATTERN.search(code):
                continue
            if not any(rel == f and frag in code for (f, frag) in _ALLOWED):
                offenders.append(f"{rel}: {line.strip()}")
    assert not offenders, offenders


def test_allowlist_entries_still_exist() -> None:
    missing = [(f, frag) for (f, frag) in _ALLOWED if frag not in (_ROOT / f).read_text(encoding="utf-8")]
    assert not missing, missing
