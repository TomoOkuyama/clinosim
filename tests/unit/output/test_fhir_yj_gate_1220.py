"""Issue #1220: JP national YJ CodeSystem gate.

The tx-server-fragment-based gate (Issue #283) downgraded 41.8 % of MR /
25.1 % of MA at JP p=10k to the JP-CLINS eCS ``nocoded`` slice because
the jpfhir-terminology 2.2606.0 CodeSystem ships as ``content=fragment``
(2000/25542 concepts, therapeutic areas 11xx/12xx only). Codes for
cardiovascular / respiratory / oncology drugs — real MHLW YJ codes —
were consequently emitted without their code semantic.

The fix checks clinosim's YJ codes against the MEDIS 医薬品HOTコードマスター
instead. Every clinosim yj.yaml code was curated to a real MHLW YJ code
(16 previously fictitious codes were replaced) so the gate passes for every
clinosim-emitted code. Since Issue #4026 the gate reads only the codes of
that master which clinosim uses (``codes/authoritative/
yj_medis_hot_used.json``), not the complete code system.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import _verified_yj_codes
from clinosim.modules.output.fhir_r4.medications.medications import _is_yj_code_valid

pytestmark = pytest.mark.unit

_SUBSET = Path(__file__).resolve().parents[3] / "clinosim" / "codes" / "authoritative" / "yj_medis_hot_used.json"


def _clinosim_yj_yaml_codes() -> set[str]:
    _path = Path(__file__).resolve().parents[3] / "clinosim" / "codes" / "data" / "yj.yaml"
    data = yaml.safe_load(_path.read_text()) or {}
    return set(data.get("codes", {}).keys())


def test_gate_loads_the_shipped_subset() -> None:
    """The gate is loaded from the shipped MEDIS-master subset, not empty
    (an empty set would downgrade every JP YJ coding to ``nocoded``)."""
    import json

    subset = json.loads(_SUBSET.read_text(encoding="utf-8"))
    codes = frozenset(c["code"] for c in subset["concept"])
    assert codes and _verified_yj_codes() == codes


def test_every_clinosim_yj_yaml_code_passes_gate() -> None:
    """Every code clinosim actually emits must be a real MHLW YJ code."""
    yaml_codes = _clinosim_yj_yaml_codes()
    assert yaml_codes, "clinosim yj.yaml is unexpectedly empty"
    unverified = [c for c in yaml_codes if not _is_yj_code_valid(c)]
    assert not unverified, (
        f"clinosim yj.yaml contains {len(unverified)} codes not in the MEDIS master: {sorted(unverified)[:10]}"
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
        assert _is_yj_code_valid(code), f"{code} should be in the MEDIS master but is not"


def test_gate_rejects_bogus_codes() -> None:
    """Sanity guard: garbage / malformed codes still fail."""
    assert not _is_yj_code_valid("NOTACODE")
    assert not _is_yj_code_valid("")
    assert not _is_yj_code_valid("1234")


def test_shipped_subset_metadata_is_semantic_honest() -> None:
    """The shipped file names the JP national registry and the MEDIS master
    edition it was checked against, and says it is a subset (no claim of a
    complete code system)."""
    import json

    meta = json.loads(_SUBSET.read_text(encoding="utf-8"))["metadata"]
    assert meta["system"] == "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code"
    assert "MEDIS" in meta["source_package"], "metadata must attribute MEDIS as source"
    assert meta["scope"].startswith("subset")
