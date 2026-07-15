"""Synthea → clinosim eval adapter (P1-10, session 46).

`Synthea <https://synthetichealth.github.io/synthea/>`_ emits its FHIR
R4 output as one JSON file per patient — the top-level document is a
FHIR Bundle whose `entry[].resource` list holds Patient / Encounter /
Observation / … objects. That's a different physical layout from the
one clinosim uses (one NDJSON per resourceType under ``fhir_r4/``),
so :mod:`clinosim.eval` cannot read Synthea output directly.

This adapter fans a directory full of Synthea Bundles into the same
layout ``clinosim eval`` expects, so the two tools can be scored with
the same 3-axis framework.

Design notes
------------
- Read-only on Synthea's side. We do not modify or repair the input.
- Deterministic ordering. Bundle files are processed in filename-sorted
  order and resources are appended in Bundle-entry order, so a
  second run against the same input directory produces byte-identical
  output NDJSON.
- No dependency on Synthea being installed. The adapter is pure Python
  + json / pathlib.

Usage
-----
    from clinosim.eval.synthea_adapter import bundle_dir_to_ndjson_layout
    bundle_dir_to_ndjson_layout("./synthea_output/fhir", "./synthea-normalized")
    # → ./synthea-normalized/fhir_r4/Patient.ndjson, Encounter.ndjson, ...

Then::

    clinosim eval -d ./synthea-normalized
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def bundle_dir_to_ndjson_layout(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    overwrite: bool = False,
) -> dict[str, int]:
    """Convert a directory of Synthea per-patient Bundles into a
    ``<output_dir>/fhir_r4/<ResourceType>.ndjson`` layout that
    :class:`clinosim.eval.EvalEngine` can consume.

    Parameters
    ----------
    input_dir
        Directory containing Synthea's ``*.json`` Bundles. Any file that
        is not a JSON Bundle is skipped silently (Synthea also writes a
        ``hospitalInformation<…>.json`` sidecar which _is_ a Bundle, so
        it's included by default).
    output_dir
        Where to write the ``fhir_r4/`` NDJSON files. Created if
        missing.
    overwrite
        When True, delete ``output_dir/fhir_r4/`` before writing.

    Returns
    -------
    dict[str, int]
        ``{ResourceType: row_count}`` after conversion.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"Synthea input directory not found: {input_dir}")

    fhir_dir = output_dir / "fhir_r4"
    if fhir_dir.exists() and overwrite:
        shutil.rmtree(fhir_dir)
    fhir_dir.mkdir(parents=True, exist_ok=True)

    # Open each output NDJSON lazily. Once we've written the first row of
    # a resourceType we keep the handle around; on function exit every
    # handle is closed via the `with ExitStack` idiom below.
    from contextlib import ExitStack

    counts: dict[str, int] = {}
    with ExitStack() as stack:
        handles: dict[str, Any] = {}

        for bundle_path in sorted(input_dir.glob("*.json")):
            try:
                bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(bundle, dict):
                continue
            if bundle.get("resourceType") != "Bundle":
                continue
            for entry in bundle.get("entry") or []:
                resource = entry.get("resource") if isinstance(entry, dict) else None
                if not isinstance(resource, dict):
                    continue
                rt = resource.get("resourceType")
                if not isinstance(rt, str) or not rt:
                    continue
                handle = handles.get(rt)
                if handle is None:
                    path = fhir_dir / f"{rt}.ndjson"
                    handle = stack.enter_context(path.open("w", encoding="utf-8"))
                    handles[rt] = handle
                handle.write(json.dumps(resource, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
                counts[rt] = counts.get(rt, 0) + 1

    return counts


def looks_like_synthea_output(path: Path | str) -> bool:
    """Cheap heuristic: does ``path`` look like a Synthea `fhir/`
    output directory rather than a clinosim ``<root>`` directory?

    True when the directory contains ``*.json`` files at the top level
    AND does **not** contain a ``fhir_r4/`` subdirectory (which is
    clinosim's marker).
    """
    p = Path(path)
    if not p.is_dir():
        return False
    if (p / "fhir_r4").exists():
        return False
    return any(p.glob("*.json"))
