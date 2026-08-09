"""FHIR snapshot diff — convert the difference between two snapshot outputs into a FHIR Bundle transaction (F3).

Operational cover for Approach C. clinosim itself stays a deterministic
snapshot generator; this module produces the Bundle that carries only
the resources that changed between two cursor positions, ready to POST
to a FHIR server. Pushing the Bundle is left to a user-side tool (curl
/ httpx / hapi-fhir-cli).
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

# Fields inside ``meta`` that depend on the cursor. Stripped before hashing.
_META_HASH_IGNORE_KEYS = ("lastUpdated", "versionId", "source")


def canonical_hash(resource: dict) -> str:
    """Canonical SHA-256 hash of a resource.

    ``meta.lastUpdated`` / ``meta.versionId`` / ``meta.source`` depend
    on the cursor, so they are stripped before hashing to prevent
    false-positive UPDATED classifications. ``meta.profile`` /
    ``meta.security`` etc. are semantic and kept.

    Dict key order is normalised by ``sort_keys=True``.
    """
    # Deep-copy so meta stripping does not mutate the caller's resource.
    stripped = copy.deepcopy(resource)
    meta = stripped.get("meta")
    if isinstance(meta, dict):
        for k in _META_HASH_IGNORE_KEYS:
            meta.pop(k, None)
        if not meta:
            stripped.pop("meta", None)
    return hashlib.sha256(json.dumps(stripped, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def classify_resources(
    old_by_id: dict[str, dict],
    new_by_id: dict[str, dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Classify every resource id into ``(new_only, updated, unchanged)``.

    ``DELETED`` (present in the old snapshot, absent in the new one) is
    normally not produced because snapshots are cumulative. If it does
    occur, the upstream caller should log a warning — this function
    intentionally does not surface it in the return tuple.

    Args:
        old_by_id: ``{id: resource}`` for the previous snapshot.
        new_by_id: ``{id: resource}`` for the current snapshot.

    Returns:
        A ``(new_only, updated, unchanged)`` triple, each a list of
        resource dicts.
    """
    new_only: list[dict] = []
    updated: list[dict] = []
    unchanged: list[dict] = []

    for rid, new_r in new_by_id.items():
        old_r = old_by_id.get(rid)
        if old_r is None:
            new_only.append(new_r)
        elif canonical_hash(old_r) != canonical_hash(new_r):
            updated.append(new_r)
        else:
            unchanged.append(new_r)

    return new_only, updated, unchanged


def load_ndjson_by_id(path: Path) -> dict[str, dict]:
    """Load a single NDJSON file into a ``{resource.id: resource}`` dict.

    Args:
        path: NDJSON file path. Returns an empty dict if the file is
            absent.

    Returns:
        ``{resource.id: resource_dict}``; resources without an ``id``
        field are dropped.
    """
    result: dict[str, dict] = {}
    if not path.exists():
        return result
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rid = r.get("id")
            if rid:
                result[rid] = r
    return result


def _iter_resource_types(directory: Path) -> Iterator[tuple[str, Path]]:
    """Yield ``(resource_type, path)`` for every ``*.ndjson`` under ``directory``.

    Args:
        directory: The directory holding the NDJSON files.

    Yields:
        ``(resource_type_from_filename, path)`` tuples.
    """
    for path in sorted(directory.glob("*.ndjson")):
        rt = path.stem
        yield rt, path


def build_diff_bundle(
    old_dir: Path,
    new_dir: Path,
    bundle_id: str,
    last_updated: str,
) -> dict:
    """Build a FHIR Bundle transaction from two snapshot output directories.

    Args:
        old_dir: Previous snapshot's FHIR NDJSON directory.
        new_dir: Current snapshot's FHIR NDJSON directory.
        bundle_id: ``Bundle.id`` to stamp on the output Bundle.
        last_updated: ``Bundle.meta.lastUpdated`` in FHIR instant format.

    Returns:
        A FHIR R4 Bundle resource of type ``transaction``. NEW
        resources are POSTed, UPDATED resources are PUT, UNCHANGED
        resources are omitted.
    """
    entries: list[dict] = []

    # Iterate every resource type present in the new dir (any type that
    # disappeared from the old dir is simply absent here).
    resource_types = {rt for rt, _ in _iter_resource_types(new_dir)}

    for rt in sorted(resource_types):
        new_by_id = load_ndjson_by_id(new_dir / f"{rt}.ndjson")
        old_by_id = load_ndjson_by_id(old_dir / f"{rt}.ndjson")

        new_only, updated, _unchanged = classify_resources(old_by_id, new_by_id)

        for r in new_only:
            entries.append(
                {
                    "resource": r,
                    "request": {"method": "POST", "url": rt},
                }
            )
        for r in updated:
            entries.append(
                {
                    "resource": r,
                    "request": {"method": "PUT", "url": f"{rt}/{r['id']}"},
                }
            )

    return {
        "resourceType": "Bundle",
        "id": bundle_id,
        "meta": {"lastUpdated": last_updated},
        "type": "transaction",
        "entry": entries,
    }


def format_summary(bundle: dict, old_cursor: str, new_cursor: str) -> str:
    """Return a human-readable summary of a Bundle transaction.

    Args:
        bundle: A FHIR R4 Bundle resource of type ``transaction``.
        old_cursor: The previous snapshot's cursor (display-only).
        new_cursor: The current snapshot's cursor (display-only).

    Returns:
        A summary text that aggregates ``new`` / ``modified`` counts
        per resource type.
    """
    entries = bundle.get("entry", [])
    new_count: Counter[str] = Counter()
    updated_count: Counter[str] = Counter()
    for e in entries:
        rt = e["resource"].get("resourceType", "?")
        method = e["request"]["method"]
        if method == "POST":
            new_count[rt] += 1
        elif method == "PUT":
            updated_count[rt] += 1

    lines = [f"Diff {old_cursor} → {new_cursor}", ""]

    if new_count:
        lines.append("New resources:")
        for rt in sorted(new_count):
            lines.append(f"  {rt:26} : {new_count[rt]}")
        lines.append("")

    if updated_count:
        lines.append("Modified resources:")
        for rt in sorted(updated_count):
            lines.append(f"  {rt:26} : {updated_count[rt]}")
        lines.append("")

    lines.append(f"Total bundle size: {len(entries)} entries")
    return "\n".join(lines)
