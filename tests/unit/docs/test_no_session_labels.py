"""Live docs carry no work-session labels.

``documentation-and-code-quality-policy.md`` §3 forbids session identifiers
("session 44", "S115") in committed docs: a reader outside the project cannot
resolve them. Write the absolute date instead (``2026-07-11``). Entry ids that
merely start with such a prefix (``s112-n10-...``) are identifiers, not labels,
and are not matched. Dated logs (history, audit cycles, reviews, design notes,
session prompts) record the past and are excluded.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]

_ARCHIVE_PREFIXES = (
    "docs/history/",
    "docs/audit-cycles/cycle-",
    "docs/audit-cycles/verification",
    "docs/reviews/",
    "docs/design-notes/",
    "docs/superpowers/",
    "docs/session-resume/",
    "docs/verify-",
)

# "session 44", "Session-102", "sessions 97-104", and "S115" for the session
# numbers in use (S100-S129); ICD-10 codes (S72.0) and seeds (s356) do not match.
_LABEL = re.compile(r"\b[Ss]essions?[- ]?\d{1,3}\b|\bS1[0-2]\d\b(?![.\d/])")


def _live_docs() -> list[Path]:
    docs = [p for p in (_ROOT / "docs").rglob("*.md") if not str(p.relative_to(_ROOT)).startswith(_ARCHIVE_PREFIXES)]
    docs += sorted(_ROOT.glob("*.md"))
    docs += list((_ROOT / "clinosim").rglob("*.md"))
    docs += list((_ROOT / "scripts").rglob("*.md"))
    return sorted(docs)


def test_live_docs_have_no_session_labels() -> None:
    hits = [
        f"{doc.relative_to(_ROOT)}:{lineno}: {match.group(0)}"
        for doc in _live_docs()
        for lineno, line in enumerate(doc.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
        for match in _LABEL.finditer(line)
    ]
    assert hits == []
