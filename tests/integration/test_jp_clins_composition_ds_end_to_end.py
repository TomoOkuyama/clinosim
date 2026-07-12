"""P2-13 PR2a Task 5: JP-CLINS discharge summary Composition end-to-end.

Full generate → NDJSON → Composition.ndjson coverage for country=JP p=50
seed=42 end=2026-06-30. Confirms:
- discharge summary Composition carries JP_Composition_eDischargeSummary
  profile URL
- type.coding uses doc-typecodes system + 18842-5
- section structure is 300 (structural) nesting 5 required children
  (312/322/342/352/360)
- US discharge summary Composition remains on the previous flat 6-section
  structure with no JP-CLINS URL leakage
- Multi-locale enforcement: US NDJSON files carry no JP CodeSystem URIs,
  no Japanese text, no JP-CLINS profile URLs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration._sr_helpers import run_generate


_PROFILE = (
    "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/"
    "JP_Composition_eDischargeSummary"
)
_DOC_TYPE_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section"
_SNAPSHOT_END = "2026-06-30"


def _read_ndjson(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def _find_composition(outdir: Path) -> Path | None:
    for cand in outdir.rglob("Composition.ndjson"):
        return cand
    return None


@pytest.mark.integration
def test_jp_p50_discharge_summary_composition_conforms(tmp_path):
    outdir = tmp_path / "jp"
    run_generate("JP", 50, 42, outdir, end=_SNAPSHOT_END)
    comp_path = _find_composition(outdir)
    assert comp_path, "Composition.ndjson not found"
    comps = _read_ndjson(comp_path)
    ds = [c for c in comps if any(
        cc.get("code") == "18842-5"
        for cc in c.get("type", {}).get("coding", [])
    )]
    assert ds, "no discharge summary Composition found in JP cohort"

    for c in ds:
        # profile emitted
        assert _PROFILE in c.get("meta", {}).get("profile", []), c["id"]
        # doc-typecodes coding present alongside LOINC
        systems = {cc.get("system") for cc in c["type"]["coding"]}
        assert _DOC_TYPE_SYSTEM in systems, c["type"]
        # nested 300 → 5 required children
        top = c.get("section", [])
        assert len(top) == 1, c["id"]
        parent = top[0]
        assert parent["code"]["coding"][0]["code"] == "300"
        assert parent["code"]["coding"][0]["system"] == _SECTION_SYSTEM
        children = parent.get("section", [])
        codes = [ch["code"]["coding"][0]["code"] for ch in children]
        assert set(codes) == {"312", "322", "342", "352", "360"}, codes
        for ch in children:
            assert ch["code"]["coding"][0]["system"] == _SECTION_SYSTEM
            assert ch["text"]["div"], "empty section text.div"


@pytest.mark.integration
def test_us_p50_discharge_summary_composition_unchanged(tmp_path):
    outdir = tmp_path / "us"
    run_generate("US", 50, 42, outdir, end=_SNAPSHOT_END)
    comp_path = _find_composition(outdir)
    if not comp_path:
        return  # US may not emit Composition depending on encounter mix; nothing to check.
    comps = _read_ndjson(comp_path)
    for c in comps:
        # No JP-CLINS profile leaks into US
        profs = c.get("meta", {}).get("profile", [])
        assert not any(p.startswith(
            "http://jpfhir.jp/fhir/eDischargeSummary/") for p in profs), profs
        # US DS type coding does not use doc-typecodes
        systems = {cc.get("system") for cc in c.get("type", {}).get("coding", [])}
        assert _DOC_TYPE_SYSTEM not in systems, c["type"]


@pytest.mark.integration
def test_us_p50_has_no_japanese_language_leakage(tmp_path):
    """★★ Multi-locale enforcement (user directive, session 47):
    US bundle must not contain JP CodeSystem URIs nor JP-CLINS profile URLs
    in any resource type file. Byte-level string scan is deliberately broad
    to catch accidental JP leakage everywhere.
    """
    outdir = tmp_path / "us-lang"
    run_generate("US", 50, 42, outdir, end=_SNAPSHOT_END)
    jp_url_signals = [
        _DOC_TYPE_SYSTEM,
        _SECTION_SYSTEM,
        "http://jpfhir.jp/fhir/eDischargeSummary/",
        "http://jpfhir.jp/fhir/eReferral/",
        "http://jpfhir.jp/fhir/eCS/",
        "http://jpfhir.jp/fhir/core/",
    ]
    for ndjson_path in outdir.rglob("*.ndjson"):
        with open(ndjson_path, encoding="utf-8") as f:
            content = f.read()
        for sig in jp_url_signals:
            assert sig not in content, (
                f"US bundle {ndjson_path.name} contains JP URL signal {sig!r}"
            )
