"""Issue #1220: full JP national YJ CodeSystem gate.

The tx-server-fragment-based gate (Issue #283) downgraded 41.8 % of MR /
25.1 % of MA at JP p=10k to the JP-CLINS eCS ``nocoded`` slice because
the jpfhir-terminology 2.2606.0 CodeSystem ships as ``content=fragment``
(2000/25542 concepts, therapeutic areas 11xx/12xx only). Codes for
cardiovascular / respiratory / oncology drugs — real MHLW YJ codes —
were consequently emitted without their code semantic.

The fix ships the full JP national YJ CodeSystem
(``clinosim/codes/authoritative/JP_MedicationCodeYJ_CS_full.json``,
``content=complete``, MEDIS-sourced, 23,923 concepts) as a clinosim
artifact and rewires the emit gate to use it. Every clinosim yj.yaml
code was curated to a real MHLW YJ code (16 previously fictitious codes
were replaced) so the gate passes for every clinosim-emitted code.
Downstream validators can load the shipped CS ahead of the tx-server
fragment to resolve the ``required`` binding on
``codingYJ.code -> JP_MedicationCodeYJ_VS|1.1.0a`` against the complete
concept set — spec-clean rather than defensive-downgrade.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.modules.output.fhir_r4.medications.medications import (
    _FULL_YJ_CODES,
    _is_yj_code_valid,
)

pytestmark = pytest.mark.unit


def _clinosim_yj_yaml_codes() -> set[str]:
    _path = Path(__file__).resolve().parents[3] / "clinosim" / "codes" / "data" / "yj.yaml"
    data = yaml.safe_load(_path.read_text()) or {}
    return set(data.get("codes", {}).keys())


def test_full_cs_loaded_with_expected_scale() -> None:
    """The MEDIS-sourced CS ships tens of thousands of concepts."""
    assert len(_FULL_YJ_CODES) > 20000, f"expected > 20k concepts, got {len(_FULL_YJ_CODES)}"


def test_every_clinosim_yj_yaml_code_passes_gate() -> None:
    """Every code clinosim actually emits must be a real MHLW YJ code."""
    yaml_codes = _clinosim_yj_yaml_codes()
    assert yaml_codes, "clinosim yj.yaml is unexpectedly empty"
    unverified = [c for c in yaml_codes if not _is_yj_code_valid(c)]
    assert not unverified, (
        f"clinosim yj.yaml contains {len(unverified)} codes not in the full MEDIS CS: {sorted(unverified)[:10]}"
    )


def test_gate_accepts_top_frequency_p10k_drugs() -> None:
    """Drugs identified as top NOCODED offenders in JP p=10k v2 audit now pass.

    Ref: Issue #1220 fork audit — Metformin / Salbutamol / Tiotropium /
    Lansoprazole / VitaminD / Levothyroxine / Carvedilol / etc.
    accounted for 14,605 (78%) of the 18,674 NOCODED occurrences.
    """
    top_codes = [
        "2149032F1099",  # Carvedilol 10mg
        "2431004F1021",  # Levothyroxine 50μg
        "2451400A1030",  # Adrenaline injection
        "2149400A1132",  # Nicardipine injection
        "2115001X1104",  # Aminophylline hydrate
    ]
    for code in top_codes:
        assert _is_yj_code_valid(code), f"{code} should be in MEDIS full CS but is not"


def test_gate_rejects_bogus_codes() -> None:
    """Sanity guard: garbage / malformed codes still fail."""
    assert not _is_yj_code_valid("NOTACODE")
    assert not _is_yj_code_valid("")
    assert not _is_yj_code_valid("1234")


def test_shipped_cs_metadata_is_semantic_honest() -> None:
    """The shipped CS canonical URL matches the JP national registry, and
    ``content=complete`` accurately describes what we ship (no lying about scope)."""
    import json

    _cs_path = (
        Path(__file__).resolve().parents[3]
        / "clinosim"
        / "codes"
        / "authoritative"
        / "JP_MedicationCodeYJ_CS_full.json"
    )
    cs = json.loads(_cs_path.read_text())
    assert cs["url"] == "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code"
    assert cs["content"] == "complete"
    assert cs["count"] == len(cs["concept"]) > 20000
    assert "MEDIS" in cs.get("copyright", ""), "copyright must attribute MEDIS as source"
