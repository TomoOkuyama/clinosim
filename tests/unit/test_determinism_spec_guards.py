"""Guards of docs/design-guides/determinism-and-rng-spec.md (Issue #2731).

Source scans: generation never uses Python's ``random`` module, never seeds
from the builtin ``hash()``, and reads the wall clock only for run metadata.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PKG = Path(__file__).resolve().parents[2] / "clinosim"

# Spec §8: no known exception.
_STDLIB_RANDOM_ALLOWED: set[str] = set()

# Spec §5: run metadata, CLI defaults and reports — not generation.
_CLOCK_ALLOWED = {
    "eval/engine.py",
    "modules/document/audit.py",
    "modules/document/narrative/passes.py",
    "modules/output/fhir_r4/builder.py",
    "modules/output/fhir_r4/lib/generator_metadata.py",
    "simulator/cli_diff.py",
    "simulator/cli_simulate.py",
    "simulator/cli_test_encounter.py",
    "simulator/enumerate.py",
    "types/output.py",  # CIFMetadata.generation_timestamp
}


def _sources() -> list[tuple[str, str]]:
    return [(str(p.relative_to(_PKG)), p.read_text(encoding="utf-8")) for p in sorted(_PKG.rglob("*.py"))]


def _code_tokens(text: str) -> list[tokenize.TokenInfo]:
    """Tokens outside comments and strings (docstrings mention the banned calls)."""
    return [
        t
        for t in tokenize.generate_tokens(io.StringIO(text).readline)
        if t.type not in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE)
    ]


def test_no_stdlib_random() -> None:
    offenders = [
        rel
        for rel, text in _sources()
        if rel not in _STDLIB_RANDOM_ALLOWED and re.search(r"^\s*(import random\b|from random import)", text, re.M)
    ]
    assert not offenders, offenders


def test_no_builtin_hash_call() -> None:
    offenders = []
    for rel, text in _sources():
        toks = _code_tokens(text)
        for prev, tok, nxt in zip([None, *toks], toks, [*toks[1:], None]):
            is_call = tok.type == tokenize.NAME and tok.string == "hash" and nxt is not None and nxt.string == "("
            is_attribute = prev is not None and prev.string in (".", "def")
            if is_call and not is_attribute:
                offenders.append(f"{rel}:{tok.start[0]}")
    assert not offenders, offenders


def test_wall_clock_only_in_run_metadata() -> None:
    offenders = []
    for rel, text in _sources():
        if rel in _CLOCK_ALLOWED:
            continue
        toks = _code_tokens(text)
        for a, b, c in zip(toks, toks[1:], toks[2:]):
            if a.string in ("datetime", "date") and b.string == "." and c.string in ("now", "today", "utcnow"):
                offenders.append(f"{rel}:{a.start[0]}")
    assert not offenders, offenders


def test_allow_lists_name_existing_files() -> None:
    for rel in _STDLIB_RANDOM_ALLOWED | _CLOCK_ALLOWED:
        assert (_PKG / rel).exists(), rel
