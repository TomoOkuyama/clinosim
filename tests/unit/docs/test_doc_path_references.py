"""Repository paths and relative links named in the live docs exist.

A doc that names a renamed or removed file (``clinosim/simulator/seeding.py``,
``tests/e2e/golden/``) or links to a moved page sends contributors looking for
something that is not there. This guard covers the docs that describe the
current system; dated logs (history, audit cycles, reviews, design notes,
session prompts) record the past and are excluded. Code comments and
reference YAML comments are held to the same rule, because they are where a
contributor lands from a stack trace.

A path that is named on purpose although it does not exist (a placeholder in
a how-to, a file a build step creates, a retired file named as retired) goes
in ``_ALLOWED`` with its reason.
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
_ROOT_DOCS = ("README.md", "README.ja.md", "AGENTS.md", "CONTRIBUTING.md", "MODULES.md")

# A path followed by a glob / template character (``hospital_*.yaml``,
# ``fhir-profiles-{country}.yaml``) is a pattern, not a file name.
_REPO_PATH = re.compile(r"(?<![\w/.-])((?:clinosim|tests|scripts|docs)/[\w./\-]++)(?![*{<\[])")
_CODE_PATH = re.compile(r"(?<![\w/.-])((?:clinosim|tests|scripts|docs)/[\w./\-]+\.(?:py|md|yaml|yml|json))")
_FILE_SUFFIXES = {"py", "md", "yaml", "yml", "json", "csv", "txt", "ndjson"}
_MD_LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)")

# (file the reference is in, path as written) -> why it is allowed to be absent.
_ALLOWED: dict[tuple[str, str], str] = {
    ("docs/add-your-country.md", "clinosim/locale/xx"): "placeholder country code in the how-to",
    ("docs/add-your-country.ja.md", "clinosim/locale/xx"): "placeholder country code in the how-to",
    (
        "docs/add-your-country.md",
        "clinosim/codes/data/fhir-profiles-xx-core.yaml",
    ): "placeholder country code in the how-to",
    (
        "docs/add-your-country.ja.md",
        "clinosim/codes/data/fhir-profiles-xx-core.yaml",
    ): "placeholder country code in the how-to",
    ("docs/CONTRIBUTING-modules.md", "clinosim/eval/axes/my_new_axis.py"): "example file the reader creates",
    ("docs/CONTRIBUTING-modules.ja.md", "clinosim/eval/axes/my_new_axis.py"): "example file the reader creates",
    ("docs/design-guides/documentation-and-code-quality-policy.md", "foo.md"): "example of a relative link",
    ("docs/design-guides/documentation-and-code-quality-policy.ja.md", "foo.md"): "example of a relative link",
    ("clinosim/dataset/README.md", "clinosim/dataset/presets"): "created by the wheel build (pyproject force-include)",
    (
        "clinosim/dataset/README.ja.md",
        "clinosim/dataset/presets",
    ): "created by the wheel build (pyproject force-include)",
    (
        "docs/architecture/architecture-notes.md",
        "clinosim/simulator/seeding.py",
    ): "dated ADR entry names the pre-#553 location next to the current one",
    (
        "docs/architecture/architecture-notes.ja.md",
        "clinosim/simulator/seeding.py",
    ): "dated ADR entry names the pre-#553 location next to the current one",
    (
        "docs/audit-cycles/by-design-registry.md",
        "docs/patient-emit-requires-encounter",
    ): "git branch name, not a path",
    (
        "docs/audit-cycles/by-design-registry.ja.md",
        "docs/patient-emit-requires-encounter",
    ): "git branch name, not a path",
    ("docs/audit-cycles/by-design-registry.md", "docs/prior-admit-cache-by-design"): "git branch name, not a path",
}


def _live_docs() -> list[Path]:
    docs = [p for p in (_ROOT / "docs").rglob("*.md") if not str(p.relative_to(_ROOT)).startswith(_ARCHIVE_PREFIXES)]
    docs += [_ROOT / name for name in _ROOT_DOCS if (_ROOT / name).exists()]
    docs += list((_ROOT / "clinosim").rglob("*.md"))
    return sorted(docs)


def _code_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.py", "*.yaml"):
        files += (_ROOT / "clinosim").rglob(pattern)
    return sorted(files)


def _exists(path: str) -> bool:
    path = re.sub(r":\d+(-\d+)?$", "", path.rstrip(".,:;)").removesuffix("/"))
    if (_ROOT / path).exists():
        return True
    # ``pkg/module.function`` names a function in ``pkg/module.py``.
    module, _, attr = path.rpartition(".")
    return attr.isidentifier() and attr not in _FILE_SUFFIXES and (_ROOT / f"{module}.py").exists()


def _missing_in_docs() -> list[str]:
    missing: list[str] = []
    for doc in _live_docs():
        rel = str(doc.relative_to(_ROOT))
        text = doc.read_text(encoding="utf-8", errors="ignore")
        for match in _REPO_PATH.finditer(text):
            path = match.group(1).rstrip(".,:;)")
            if not _exists(path) and (rel, path) not in _ALLOWED:
                missing.append(f"{rel}: {path}")
        for match in _MD_LINK.finditer(text):
            target = match.group(1)
            if target.startswith(("http:", "https:", "mailto:")):
                continue
            if not (doc.parent / target).exists() and (rel, target) not in _ALLOWED:
                missing.append(f"{rel}: link {target}")
    return sorted(set(missing))


def _missing_in_code() -> list[str]:
    missing: list[str] = []
    for f in _code_files():
        rel = str(f.relative_to(_ROOT))
        for lineno, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for match in _CODE_PATH.finditer(line):
                path = match.group(1).rstrip(".")
                if not _exists(path) and (rel, path) not in _ALLOWED:
                    missing.append(f"{rel}:{lineno}: {path}")
    return sorted(set(missing))


def test_live_docs_name_only_existing_paths() -> None:
    assert _missing_in_docs() == []


def test_code_comments_name_only_existing_paths() -> None:
    assert _missing_in_code() == []


def test_allowlist_entries_are_still_needed() -> None:
    """An allowlisted reference that no longer appears is dead weight."""
    for (rel, path), _why in _ALLOWED.items():
        text = (_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        assert path in text, f"{rel} no longer names {path}; drop it from _ALLOWED"
