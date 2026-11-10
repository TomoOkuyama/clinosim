"""MkDocs hook: point links to repository files outside the site at GitHub.

The docs site transcludes root files (README.md, MODULES.md, CONTRIBUTING.md,
CHANGELOG.md, ...) through ``mkdocs-include-markdown-plugin``, and many pages
link to source files (``clinosim/modules/.../README.md``, ``.py`` files,
``.github/...``). Those links are relative repository paths: correct on
GitHub, but not documentation files of the site, so ``mkdocs build --strict``
rejects them. Rather than give every transcluded file dual-purpose paths,
this hook rewrites, after the includes have been expanded, every relative
link whose target is not a page of the site into the GitHub URL of that
repository path (``<repo_url>/blob/<branch>/<path>``; ``tree`` for a
directory). A link to a site page, an anchor or an external URL is left
alone, and a target that does not exist in the repository is left as written
so the strict build still reports it.

Registered in ``mkdocs.yml`` under ``hooks:``.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import Any

# Inline links and images: ``[text](target)`` / ``![alt](target "title")``;
# the link text may wrap across lines.
_LINK = re.compile(r"(!?\[[^\]]*\]\()(<[^>\n]+>|[^)\s]+)((?:\s+\"[^\"]*\")?\))")
_BRANCH = "master"


def _rewrite(target: str, page_dir: str, docs_dir: Path, repo_root: Path, site_pages: set[str], repo_url: str) -> str:
    if not target or target.startswith(("#", "/", "mailto:")) or re.match(r"^[a-z][a-z0-9+.-]*:", target):
        return target
    path, sep, anchor = target.partition("#")
    if not path:
        return target
    in_docs = posixpath.normpath(posixpath.join(page_dir, path))
    if in_docs in site_pages:
        return target
    repo_path = (docs_dir / in_docs).resolve()
    try:
        rel = repo_path.relative_to(repo_root).as_posix()
    except ValueError:
        return target  # outside the repository
    if not repo_path.exists():
        return target  # a broken link stays visible to the strict build
    kind = "tree" if repo_path.is_dir() else "blob"
    return f"{repo_url.rstrip('/')}/{kind}/{_BRANCH}/{rel}" + (sep + anchor if sep else "")


def on_page_markdown(markdown: str, page: Any, config: Any, files: Any) -> str:
    docs_dir = Path(config["docs_dir"]).resolve()
    repo_root = Path(config["config_file_path"]).resolve().parent
    repo_url = str(config.get("repo_url") or "")
    if not repo_url:
        return markdown
    site_pages = {f.src_uri for f in files.documentation_pages()} | {
        f.src_uri for f in files if not f.is_documentation_page()
    }
    page_dir = posixpath.dirname(page.file.src_uri)

    def sub(m: re.Match[str]) -> str:
        raw = m.group(2)
        bracketed = raw.startswith("<") and raw.endswith(">")
        target = raw[1:-1] if bracketed else raw
        new = _rewrite(target, page_dir, docs_dir, repo_root, site_pages, repo_url)
        if new == target:
            return m.group(0)
        return f"{m.group(1)}{'<' + new + '>' if bracketed else new}{m.group(3)}"

    # Leave fenced code blocks untouched.
    parts = re.split(r"(^```.*?^```\s*$)", markdown, flags=re.MULTILINE | re.DOTALL)
    return "".join(p if p.startswith("```") else _LINK.sub(sub, p) for p in parts)
