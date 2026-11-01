"""No Japanese string literal in Python outside the allowlist (Issue #2277).

User-facing Japanese and English text lives in the YAML catalogs and code
tables, read through ``clinosim.locale`` and ``clinosim.codes``. What stays in
code is text that parses input (keyword matchers, regexes), CLI help, and
exception messages; each such literal is pinned below by file and value, so a
new one fails here with the file and line to move into a catalog.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import clinosim

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_JP = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

_ALLOWED: dict[str, set[str]] = {
    # the Japanese-character regex
    "audit/axes/jp_language.py": {"[぀-ゟ゠-ヿ㐀-䶿一-鿿ｦ-ﾟ]"},
    # the Japanese-character regex and the audit self-test fixtures
    "modules/document/audit.py": {
        "General: 意識清明. Cardiovascular: regular rate, no murmurs.",
        "[぀-ゟ゠-ヿ一-鿿]",
        "このテキストは structural CIF に leak してはならない。",
        "胸痛",
    },
    # keywords matched against input text
    "modules/document/narrative/_patient_info_renderers.py": {"就業中"},
    # keywords matched against input text
    "modules/document/narrative/context.py": {"エリスロマイシン", "フィトナジオン", "代謝異常"},
    # keywords matched against input text
    "modules/document/narrative/renderers/_composers.py": {"呼吸音清明", "意識清明"},
    # keywords matched against input text
    "modules/document/narrative/renderers/section_builders/mortality.py": {"心肺蘇生", "蘇生"},
    # keywords matched against input text
    "modules/document/narrative/renderers/section_builders/op_pn_notes.py": {"アプローチ"},
    # a leakage-detection pattern
    "modules/document/narrative/semantic_check.py": {"改善後のセクション本文"},
    # regexes that parse ordered imaging names
    "modules/imaging/inference.py": {
        "(?:ultrasound|us)|下肢",
        "(?:ultrasound|us)|軟部",
        "(?:x|レ)",
        "(?:線|p)",
        "(?:線|p)|(?:腰椎|頸椎|胸椎)",
        "(?:線|ray|p)|レ|レントゲン)|胸写|胸",
        "(?:線|ray|p)|腹部",
        "(?:超音波|エコー)",
        "(?:超音波|エコー|us)",
        "(?:関節)?",
        "?contrast)?|軟部",
        "^(?:ecg|ekg)(?:[\\s\\-_].*)?$|心電図",
        "angio(?:graphy|gram)|ctpa|肺動脈",
        "angio(?:graphy|gram)|冠動脈",
        "ct|脳",
        "ct|腎臓",
        "mri|(?:腰椎|頸椎|胸椎)",
        "mri|脳",
        "x[\\s\\-_]*(?:線|ray|p)|胸部",
        "下肢",
        "単純",
        "手",
        "手関節",
        "股関節",
        "胸部",
        "脊椎",
        "腎",
        "腹部",
        "造影",
        "静脈",
        "頭部",
    },
    # keywords matched against input text
    "modules/order/engine.py": {" または "},
    # keywords that classify protocol text
    "modules/order/treatment_classifier.py": {"parkland式", "抗凝固療法 (置換", "治療的抗凝固療法", "置換 予防投与"},
    # keywords matched against input text
    "modules/output/fhir_r4/encounters/encounter.py": {"フォローアップ", "予防接種", "健康診断"},
    # keywords matched against input text
    "modules/output/fhir_r4/encounters/facility.py": {"回復期"},
    # keywords matched against input text
    "modules/output/fhir_r4/procedures/immunization.py": {"予防接種", "小児"},
    # keywords matched against input text
    "modules/output/fhir_r4/procedures/oxygen_therapy.py": {"目標"},
    # --help text naming the Japanese insurance fields
    "simulator/cli.py": {"  JP insurance numbers (被保険者番号): "},
    # --help text
    "simulator/cli_narrate.py": {
        "'. Narrative text is generated in the country's language (JP → 日本語, US → English); a mismatch would produce wrong-language narratives against the structural CIF. Re-run with --country "  # noqa: E501
    },
}


def _japanese_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    skip |= {id(c) for r in ast.walk(tree) if isinstance(r, ast.Raise) for c in ast.walk(r)}
    return [
        (n.lineno, n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip and _JP.search(n.value)
    ]


def test_no_new_japanese_literal() -> None:
    new = []
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        allowed = _ALLOWED.get(rel, set())
        new += [f"{rel}:{line} {value[:40]!r}" for line, value in _japanese_literals(path) if value not in allowed]
    assert not new, "Move these into a catalog (locale/shared/*.yaml) or a code table:\n" + "\n".join(new)


def test_allowlist_has_no_stale_entry() -> None:
    stale = []
    for rel, values in _ALLOWED.items():
        path = _ROOT / rel
        present = {v for _, v in _japanese_literals(path)} if path.exists() else set()
        stale += [f"{rel} {v!r}" for v in values - present]
    assert not stale, stale
