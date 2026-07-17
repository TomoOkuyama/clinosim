r"""Emit a sidecar `_generator_metadata.json` next to the FHIR NDJSON export.

## Rationale

FHIR consumers (HAPI validator, downstream ingestion pipelines,
fhir-jp-validator) need to know **which clinosim revision generated a
given export** so they can correlate observed validation results with the
fix-PRs already applied. Baking that metadata into the FHIR resources
themselves would violate the profiles (extensions on Bundle / Patient
/ etc. are not allowed for provenance-of-generator), so we write a
sidecar file to the same output directory.

## File name and shape

The sidecar is `_generator_metadata.json`. The leading underscore keeps
it out of the FHIR resource-type namespace (no FHIR resource type starts
with `_`) so tools that iterate the export by "everything ending in
`.json`" or by `manifest.json.output[*]` will not mistake it for a
resource file.

Shape:

```json
{
  "clinosim_version": "0.2.0",
  "generated_at": "2026-07-17T12:34:56+09:00",
  "country": "JP",
  "cif_metadata": { ... verbatim from cif/metadata.json ... },
  "git": {
    "commit": "abc123def456...",
    "commit_short": "abc123d",
    "commit_datetime": "2026-07-17T10:39:31+09:00",
    "commit_subject": "fix(fhir): ...",
    "dirty": false
  },
  "recent_merges": [
    {"pr": 205, "subject": "fix(fhir): map informal clinical unit spellings..."},
    ...
  ]
}
```

`recent_merges` is populated from `git log --oneline --grep '(#\d+)'`
capped at 30 entries — enough to cover recent fix chains without bloating
the sidecar. Each entry records the PR number (extracted from the merge
commit subject) and the trailing subject text.

## Failure behavior

Git introspection is best-effort. If the export runs from an sdist (no
`.git` directory) or `git` is not on PATH, the `git` and `recent_merges`
fields are set to `null` / `[]` and the sidecar is still written. The
sidecar write itself is soft-failure: an OSError is logged via
`sim_log.info` and swallowed so a filesystem hiccup does not fail the
whole export.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from clinosim import __version__ as _clinosim_version
from clinosim.simulator import log as sim_log

_CLINOSIM_VERSION: str = _clinosim_version

_SIDECAR_FILENAME = "_generator_metadata.json"
_RECENT_MERGES_LIMIT = 30
# Match `... (#123)` or `... (#123) (#456)` — the trailing `(#N)` on
# GitHub squash-merge commit subjects. The right-most `#N` is the PR
# number of the merge that landed on `master`.
_PR_NUMBER_RE = re.compile(r"\(#(\d+)\)\s*$")


def _run_git(args: list[str], cwd: Path) -> str | None:
    """Run ``git <args>`` in ``cwd``; return stdout or None on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    return result.stdout.strip() or None


def _collect_git_info(repo_root: Path) -> dict[str, Any] | None:
    """Best-effort ``git`` introspection. Returns None if not a git repo."""
    head = _run_git(["rev-parse", "HEAD"], repo_root)
    if head is None:
        return None
    subject = _run_git(["log", "-1", "--pretty=%s"], repo_root) or ""
    commit_dt = _run_git(["log", "-1", "--pretty=%cI"], repo_root) or ""
    dirty_probe = _run_git(["status", "--porcelain"], repo_root)
    dirty = bool(dirty_probe)
    return {
        "commit": head,
        "commit_short": head[:8],
        "commit_datetime": commit_dt,
        "commit_subject": subject,
        "dirty": dirty,
    }


def _collect_recent_merges(repo_root: Path, limit: int = _RECENT_MERGES_LIMIT) -> list[dict[str, Any]]:
    """Return the ``limit`` most recent PR merges as ``[{"pr": N, "subject": "..."}]``.

    Reads ``git log --oneline`` and picks lines whose subject ends in
    ``(#N)``. Empty list if git is unavailable.
    """
    log_output = _run_git(["log", "--oneline", f"-{limit * 3}"], repo_root)
    if not log_output:
        return []
    merges: list[dict[str, Any]] = []
    for line in log_output.splitlines():
        # `git log --oneline` format: "<short-sha> <subject>"
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        subject = parts[1]
        m = _PR_NUMBER_RE.search(subject)
        if not m:
            continue
        merges.append({"pr": int(m.group(1)), "subject": subject})
        if len(merges) >= limit:
            break
    return merges


def _find_repo_root() -> Path | None:
    """Walk up from this file to the nearest ``.git`` directory. Return None
    if run from an installed wheel/sdist (no ``.git`` in any ancestor)."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _load_cif_metadata(cif_dir: str) -> dict[str, Any]:
    """Load ``cif/metadata.json`` if present, empty dict otherwise.

    The CIF writer already records ``random_seed`` / ``snapshot_date`` /
    ``total_patients_generated`` / ``hospital_scale`` / ``llm_mode`` etc.
    Forwarding it verbatim keeps the sim-params info in one canonical
    shape rather than reinventing a subset here.
    """
    path = os.path.join(cif_dir, "metadata.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_generator_metadata(
    output_dir: str,
    cif_dir: str,
    country: str,
) -> str | None:
    """Write the ``_generator_metadata.json`` sidecar. Return its path or None
    on failure (soft-failure; export loop continues).

    Called from ``convert_cif_to_fhir`` right after ``manifest.json`` is
    written so both files land together in the export directory.
    """
    repo_root = _find_repo_root()
    git_info = _collect_git_info(repo_root) if repo_root else None
    recent = _collect_recent_merges(repo_root) if repo_root else []
    payload: dict[str, Any] = {
        "clinosim_version": _CLINOSIM_VERSION,
        "generated_at": datetime.now(UTC).astimezone().isoformat(),
        "country": country,
        "cif_metadata": _load_cif_metadata(cif_dir),
        "git": git_info,
        "recent_merges": recent,
    }
    path = os.path.join(output_dir, _SIDECAR_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        sim_log.info(
            "fhir_r4_adapter",
            "generator_metadata_write_failed",
            path=path,
            error=str(exc),
        )
        return None
    sim_log.info(
        "fhir_r4_adapter",
        "generator_metadata_written",
        path=path,
        clinosim_version=_CLINOSIM_VERSION,
        git_commit=(git_info or {}).get("commit_short"),
        recent_merges=len(recent),
    )
    return path
