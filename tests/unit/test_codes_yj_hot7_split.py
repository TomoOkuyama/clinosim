"""Unit tests for Issue #415: yj.yaml → yj.yaml + hot7.yaml split.

Pins:

- ``yj.yaml`` holds ONLY YJ12 codes (12-char format ``\\d{7}[A-Z]\\d{4}``);
  ``hot7.yaml`` holds ONLY HOT7 codes (7-digit format ``\\d{7}``). Neither
  contains codes matching the other's format.
- ``get_system_uri("yj")`` = capstandard YJ-code URI (unchanged).
- ``get_system_uri("hot7")`` = MEDIS master-HOT7 URI (unchanged from
  ``_BUILTIN_URIS``).
- ``lookup("yj", <HOT7 code>)`` falls through to ``hot7.yaml`` and
  returns the correct display, so existing emit consumers that call
  ``lookup(system_key_for("drug", "JP") = "yj", code, lang)`` continue
  to resolve display for both HOT7 and YJ12 codes without changes.
- ``lookup("hot7", <HOT7 code>)`` returns the display directly.
- ``lookup("yj", <YJ12 code>)`` returns the display directly (no fallthrough).
- Sibling fallback is display-only: ``get_system_uri`` is NEVER routed
  through siblings (each system keeps its own canonical URI).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from clinosim.codes import get_system_uri, lookup

pytestmark = pytest.mark.unit

_DATA_DIR = Path(__file__).parent.parent.parent / "clinosim" / "codes" / "data"
_YJ_FILE = _DATA_DIR / "yj.yaml"
_HOT7_FILE = _DATA_DIR / "hot7.yaml"

_HOT7_PATTERN = re.compile(r"^\d{7}$")
_YJ12_PATTERN = re.compile(r"^\d{7}[A-Z]\d{4}$")


def _load(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


# ────────────────────────────────────────────────────────────────────
# File separation


class TestFileSeparation:
    def test_yj_yaml_only_holds_yj12_codes(self):
        d = _load(_YJ_FILE)
        codes = list((d.get("codes") or {}).keys())
        assert len(codes) > 0, "yj.yaml must not be empty"
        non_yj12 = [c for c in codes if not _YJ12_PATTERN.match(c)]
        assert not non_yj12, f"yj.yaml MUST only hold YJ12 codes. Non-YJ12 codes found: {non_yj12[:5]}"

    def test_hot7_yaml_registers_no_yj_prefixes(self):
        """Issue #2347: every 7-digit code hot7.yaml held was the first seven
        characters of a YJ code (the MHLW ingredient prefix), not a MEDIS
        HOT7 number. JP drug codes are now full YJ codes from the drug
        catalog, and hot7.yaml registers none until verified HOT codes land."""
        assert not (_load(_HOT7_FILE).get("codes") or {})

    def test_yj_and_hot7_registries_do_not_overlap(self):
        yj = set((_load(_YJ_FILE).get("codes") or {}).keys())
        hot7 = set((_load(_HOT7_FILE).get("codes") or {}).keys())
        overlap = yj & hot7
        assert not overlap, f"yj.yaml and hot7.yaml MUST NOT overlap: {overlap}"

    def test_split_preserves_total_count(self):
        """Session 81 split moved 106 HOT7 codes out and left 59 YJ12
        codes. Issue #1233 (2026-09-10): +17 real MEDIS YJ codes for
        oncology / endocrine / supplements to cure JP p=10k NOCODED
        residual → 76 YJ12. If a future PR adds/removes drug data these
        counts change — update this test with the new totals rather than
        removing the pin (the counts document the split's intent).

        History since v0.6.1 (s107 continued):
        - #1296 (SSRI): +3 (Sertraline / Escitalopram / Paroxetine) → 109.
        - #1297 (C-section intraop bundle): +4 (Oxytocin / Bupivacaine /
          Ketorolac / Ondansetron) → 113. Ketorolac + Ondansetron were
          already referenced from the JP `code_mapping_drug.yaml` but
          missing from hot7 display; that backfill is what took the
          count to 113 rather than 111.
        - #1281 second follow-up (SNRI+atypical antidepressants): +1
          Fluvoxamine (1179038). Duloxetine / Venlafaxine / Mirtazapine
          JP YJ codes deferred until per-code verification lands. → 114.
        - #1280 sub-C (chemo drug catalog expansion): +5 (Gemcitabine
          4224400 / Irinotecan 4240401 / Nab-paclitaxel 4291423 /
          Temozolomide 4291023 / BCG 6323400). All PMDA-approved
          oncology drugs. Regimen wiring for C22 / C25 / C67 / C71
          deferred to follow-up. → 119.
        - #2134 (YJ class codes naming another drug): entries re-keyed to
          the correct classes; −2 (Ketorolac 1149029 — not marketed in
          Japan; 6139002 — a tebipenem class labelled meropenem), +4
          (Duloxetine 1179052, Ampicillin 6131400, Norepinephrine
          2451401, Morphine 8114401) → 121.
        - #2136 (JP NOCODED drugs + JP alternatives for drugs not marketed
          in Japan): +20 (incl. S-1 4229101) → 141.
        - #2140 (schizophrenia): +4 second-generation antipsychotics → 145.
        - #2142 (bipolar disorder): +3 mood stabilizers → 148.
        - #2148 (psychotic / manic crisis): +1 haloperidol injection → 149.
        - #2155 (ED discharge prescriptions): +6 (Cetirizine / Hydroxyzine /
          Loperamide / Sumatriptan / Naproxen / Dextromethorphan) → 155.
        - #2347: the 155 "HOT7" codes were YJ ingredient prefixes; all removed
          (hot7 → 0). The drug catalog's full YJ products are registered in
          yj.yaml with their MHLW product names (yj → 254).
        """
        yj_n = len(_load(_YJ_FILE).get("codes") or {})
        hot7_n = len(_load(_HOT7_FILE).get("codes") or {})
        assert yj_n == 254, f"yj.yaml YJ12 count expected 254, got {yj_n}"
        assert hot7_n == 0, f"hot7.yaml HOT7 count expected 0, got {hot7_n}"


# ────────────────────────────────────────────────────────────────────
# URIs


class TestSystemUris:
    def test_yj_uri_is_capstandard(self):
        assert get_system_uri("yj") == "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code"

    def test_hot7_uri_is_medis(self):
        assert get_system_uri("hot7") == "http://medis.or.jp/CodeSystem/master-HOT7"

    def test_sibling_fallback_does_not_leak_uri(self):
        """URIs are per-system and MUST NOT flow through the display
        fallback. If a future refactor accidentally makes ``yj``'s URI
        return HOT7's (or vice versa), this catches it."""
        assert get_system_uri("yj") != get_system_uri("hot7")


# ────────────────────────────────────────────────────────────────────
# Backward-compat display lookup


class TestBackwardCompatLookup:
    def test_yj_key_still_resolves_yj12_code(self):
        # Ampicillin/Sulbactam YJ12 code — stays in yj.yaml
        assert lookup("yj", "6139504G1028", "ja") == "アンピシリン/スルバクタム（ユナシン）"

    def test_hot7_key_does_not_resolve_yj12_code(self):
        """Sibling fallback is directional (yj → hot7), NOT the reverse.
        A YJ12 code queried via ``"hot7"`` MUST NOT resolve because
        that would let a caller mislabel a YJ12 code as HOT7."""
        # Returns the code itself when unresolved.
        assert lookup("hot7", "6139504G1028", "ja") == "6139504G1028"

    def test_unknown_code_returns_code_as_fallback(self):
        """Unknown code through the yj → hot7 chain still returns the
        original code (no crash on missing entries)."""
        assert lookup("yj", "9999999", "ja") == "9999999"
