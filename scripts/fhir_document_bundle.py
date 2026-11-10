"""Document Bundles for the HL7 validator bridges (Issue #3147).

A document Composition's entry slices (JP-CLINS eReferral 920 / 910
organizations, discharge-summary and health-checkup sections) are matched by
resolving the referenced resource's profile, which a Composition validated
on its own cannot do. ``validate_jp.sh`` therefore validates each sampled
Composition inside a ``type: document`` Bundle: the Composition first, then
every resource it references, directly or through those resources, taken
from the cohort's NDJSON files.

Usage (from the bridges)::

    python3 scripts/fhir_document_bundle.py <fhir_dir> <composition.json> <out.json>

writes the Bundle and prints its size and any reference the cohort does not
resolve (none expected).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

# Base of every entry's fullUrl: a relative reference "Patient/p1" resolves
# to the entry whose fullUrl is <base>/Patient/p1.
FULL_URL_BASE = "http://clinosim.example/fhir"


def _references(node: Any) -> list[str]:
    """Every relative literal reference ("Type/id") inside ``node``."""
    out: list[str] = []
    if isinstance(node, dict):
        ref = node.get("reference")
        if isinstance(ref, str) and "/" in ref and not ref.startswith(("#", "urn:", "http")):
            out.append(ref)
        for value in node.values():
            out.extend(_references(value))
    elif isinstance(node, list):
        for value in node:
            out.extend(_references(value))
    return out


def _key(resource: dict[str, Any]) -> str:
    return f"{resource['resourceType']}/{resource['id']}"


def document_bundle(composition: dict[str, Any], index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A document Bundle holding ``composition`` and the transitive closure
    of the resources it references that ``index`` ("Type/id" -> resource)
    holds."""
    ordered = [composition]
    seen = {_key(composition)}
    queue = list(_references(composition))
    while queue:
        ref = queue.pop(0)
        if ref in seen or ref not in index:
            continue
        seen.add(ref)
        ordered.append(index[ref])
        queue.extend(_references(index[ref]))
    return {
        "resourceType": "Bundle",
        "identifier": {
            "system": "urn:ietf:rfc:3986",
            "value": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, FULL_URL_BASE + '/' + _key(composition))}",
        },
        "type": "document",
        "timestamp": composition.get("date") or "1970-01-01T00:00:00Z",
        "entry": [{"fullUrl": f"{FULL_URL_BASE}/{_key(r)}", "resource": r} for r in ordered],
    }


def missing_references(bundle: dict[str, Any]) -> list[str]:
    """References inside the Bundle that no entry resolves."""
    present = {_key(e["resource"]) for e in bundle["entry"]}
    refs = {ref for e in bundle["entry"] for ref in _references(e["resource"])}
    return sorted(refs - present)


def declares_profile(bundle: dict[str, Any], profile: str) -> bool:
    """Whether the Bundle's Composition declares ``profile`` in meta.profile."""
    profiles = (bundle["entry"][0]["resource"].get("meta") or {}).get("profile") or []
    return any(str(p).split("|")[0] == profile for p in profiles)


def index_ndjson(fhir_dir: Path) -> dict[str, dict[str, Any]]:
    """Every resource of the cohort's NDJSON files, by "Type/id"."""
    index: dict[str, dict[str, Any]] = {}
    for path in sorted(fhir_dir.rglob("*.ndjson")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    resource = json.loads(line)
                    index[_key(resource)] = resource
    return index


def main(argv: list[str]) -> int:
    fhir_dir, composition_path, out_path = Path(argv[1]), Path(argv[2]), Path(argv[3])
    composition = json.loads(composition_path.read_text(encoding="utf-8"))
    bundle = document_bundle(composition, index_ndjson(fhir_dir))
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    missing = missing_references(bundle)
    print(f"  document Bundle: {len(bundle['entry'])} resources" + (f", missing {missing}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
