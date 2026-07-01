"""AD-65 Bug A integration test — US ADMISSION_HP must be English-only.

Bug A ("US H&P Japanese contamination"): pre-fix, every ADMISSION_HP (LOINC
34117-2) HPI + Physical Examination section emitted Japanese text for US
(en-locale) cohorts, because several `template_generator.py` builders read a
`_ja`-suffixed field unconditionally. Task 9 fixed the locale-routing bug via
`_pick_localized(tmpl, key_base, lang)`; Task 10 populated missing `_en` YAML
peers for every field that carries a per-language split.

Two sections ("hpi", "physical_examination") are a *known, separate,
deferred* gap: their disease-YAML source data (`hpi_template.onset_pattern` /
`physical_exam_findings`) carries no per-language split at ALL (not even a
`_ja`/`_en` pair to route between) across any of the 32 disease YAMLs. Task 9
tags this with `facts_used: "...:ja_only_fallback"` (see
`template_generator.py:_build_hpi` / `_build_physical_examination`) rather
than fabricating English text. This is explicitly out of scope for the Bug A
code/YAML fixes (see `.superpowers/sdd/task-9-report.md` §6 concern 2 and
`task-10-report.md` §7) and is tracked separately (TODO.md "disease YAML
English narrative content"). This test therefore excludes those two sections
from the strict zero-ja-chars assertion — see
`clinosim.modules.document.audit.KNOWN_JA_ONLY_FALLBACK_SECTIONS` (single
source of truth, shared with the `us_admission_hp_zero_ja_chars` audit gate).

Any OTHER ADMISSION_HP section containing Japanese characters indicates a
genuine Bug-A-class locale-routing regression and MUST fail this test.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from clinosim.modules.document.audit import (
    KNOWN_JA_ONLY_FALLBACK_SECTIONS,
    _count_us_hp_ja_chars,
)

JA_CHAR_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")


@pytest.mark.integration
def test_us_admission_hp_zero_japanese_chars(tmp_path: Path) -> None:
    """Generate a US p=100 cohort and verify ADMISSION_HP is English-only.

    p=100 reliably produces a handful of inpatient (and therefore
    ADMISSION_HP) encounters for the default hospital config / seed; if a
    future config change drops inpatient volume to zero at this population
    size, the test skips rather than passing vacuously.
    """
    out = tmp_path / "us100"
    r = subprocess.run(
        [
            sys.executable, "-m", "clinosim.simulator.cli", "generate",
            "-p", "100", "--country", "US", "-o", str(out),
            "--format", "cif", "fhir-r4",
        ],
        capture_output=True, text=True, timeout=600,
    )
    assert r.returncode == 0, r.stderr

    comp_path = out / "fhir_r4" / "Composition.ndjson"
    assert comp_path.exists(), f"no Composition.ndjson: {r.stdout[-500:]}"

    # --- Primary check: CIF narrative tree, via the shared audit helper
    # (single source of truth with the `us_admission_hp_zero_ja_chars` audit
    # gate in clinosim/modules/document/audit.py — AD-65 / DRY). ---
    cif_ja_count = _count_us_hp_ja_chars(str(out / "cif"))

    # --- Secondary check: same invariant re-derived independently from the
    # FHIR Composition output, confirming the CIF -> FHIR no-drop pathway
    # doesn't reintroduce (or silently lose track of) Japanese contamination
    # between the two representations. ---
    fhir_ja_count = 0
    n_hp = 0
    for line in comp_path.read_text().splitlines():
        d = json.loads(line)
        codings = d.get("type", {}).get("coding", [])
        if not any(c.get("code") == "34117-2" for c in codings):
            continue
        n_hp += 1
        for section in d.get("section", []):
            title = section.get("title", "")
            if title in KNOWN_JA_ONLY_FALLBACK_SECTIONS:
                continue
            div = section.get("text", {}).get("div", "")
            fhir_ja_count += len(JA_CHAR_RE.findall(div))

    if n_hp == 0:
        pytest.skip(
            "no ADMISSION_HP (LOINC 34117-2) Compositions generated at p=100 "
            "for this seed/config (no inpatient encounters) — cannot exercise "
            "the Bug A assertion vacuously"
        )

    assert cif_ja_count == 0, (
        f"US ADMISSION_HP CIF narrative tree contains {cif_ja_count} "
        f"untagged Japanese chars (sections other than "
        f"{sorted(KNOWN_JA_ONLY_FALLBACK_SECTIONS)}) — Bug A regression"
    )
    assert fhir_ja_count == 0, (
        f"US ADMISSION_HP FHIR Composition contains {fhir_ja_count} "
        f"untagged Japanese chars across {n_hp} H&P document(s) (sections "
        f"other than {sorted(KNOWN_JA_ONLY_FALLBACK_SECTIONS)}) — Bug A regression"
    )
