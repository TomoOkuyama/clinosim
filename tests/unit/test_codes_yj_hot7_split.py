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

    def test_hot7_yaml_only_holds_hot7_codes(self):
        d = _load(_HOT7_FILE)
        codes = list((d.get("codes") or {}).keys())
        assert len(codes) > 0, "hot7.yaml must not be empty"
        non_hot7 = [c for c in codes if not _HOT7_PATTERN.match(c)]
        assert not non_hot7, f"hot7.yaml MUST only hold HOT7 codes. Non-HOT7 codes found: {non_hot7[:5]}"

    def test_yj_and_hot7_registries_do_not_overlap(self):
        yj = set((_load(_YJ_FILE).get("codes") or {}).keys())
        hot7 = set((_load(_HOT7_FILE).get("codes") or {}).keys())
        overlap = yj & hot7
        assert not overlap, f"yj.yaml and hot7.yaml MUST NOT overlap: {overlap}"

    def test_split_preserves_total_count(self):
        """Session 81 split moved 106 HOT7 codes out and left 59 YJ12
        codes. If a future PR adds/removes drug data these counts change
        — update this test with the new totals rather than removing the
        pin (the counts document the split's intent)."""
        yj_n = len(_load(_YJ_FILE).get("codes") or {})
        hot7_n = len(_load(_HOT7_FILE).get("codes") or {})
        assert yj_n == 59, f"yj.yaml YJ12 count expected 59, got {yj_n}"
        assert hot7_n == 106, f"hot7.yaml HOT7 count expected 106, got {hot7_n}"


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
    def test_yj_key_resolves_hot7_code_display_ja(self):
        """Emit consumers call ``lookup(system_key_for("drug", "JP") = "yj", code, "ja")``
        with BOTH HOT7 and YJ12 codes. The sibling fallback keeps HOT7 lookups
        working via the ``"yj"`` key after the split."""
        # Amoxicillin (Amoxil) HOT7 code — moved from yj.yaml to hot7.yaml
        display = lookup("yj", "6131002", "ja")
        assert display == "アモキシシリン（サワシリン）", (
            f"HOT7 code via 'yj' key MUST fall through to hot7.yaml, got {display!r}"
        )

    def test_yj_key_resolves_hot7_code_display_en(self):
        display = lookup("yj", "6131002", "en")
        assert display == "Amoxicillin (Amoxil)", f"HOT7 code via 'yj' key EN fallback failed, got {display!r}"

    def test_yj_key_still_resolves_yj12_code(self):
        # Ampicillin/Sulbactam YJ12 code — stays in yj.yaml
        assert lookup("yj", "6139504G1028", "ja") == "アンピシリン/スルバクタム（ユナシン）"

    def test_hot7_key_resolves_directly(self):
        """Callers that migrate to the ``"hot7"`` key work identically."""
        assert lookup("hot7", "6131002", "ja") == "アモキシシリン（サワシリン）"
        assert lookup("hot7", "6131002", "en") == "Amoxicillin (Amoxil)"

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
