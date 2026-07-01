"""CIFReader — Two-pass CIF merge loader (AD-65 Task 4).

All FHIR / CSV adapters read patient records via this reader instead of
walking ``structural/patients/*.json`` directly. Narrative content written by
a NarrativePass (``cif/narratives/<version>/documents/<enc>/<doc_id>.json``,
Task 3) is merged into the matching structural stub's ``narrative`` field at
read time, so downstream builders always see the two-layer CIF as a single
merged dict tree (spec §"CIF file layout on disk (two-layer)").

Merge semantics:
  - Missing ``narratives/`` directory entirely -> stubs are left as-is
    (``narrative`` stays whatever the structural file already has, typically
    ``None``).
  - Missing per-encounter narrative directory (no documents were generated
    for that encounter, or the pass hasn't run yet) -> same no-op behaviour.
  - Narrative file whose ``document_id`` has no matching structural stub
    (orphan — e.g. stale narrative version pointing at a doc since removed
    from a disease/encounter YAML) -> warn + drop (never invent a stub).

``narrative_version="current"`` resolves via the ``current_version.txt``
pointer file (``cif/narratives/current_version.txt``); a missing pointer
falls back to ``"template"`` (the Stage 2 default writer, Task 3).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_NARRATIVE_VERSION_FALLBACK = "template"


class CIFReader:
    """Single load path for two-layer CIF (structural + narrative)."""

    def __init__(self, cif_dir: str, narrative_version: str = "current"):
        self.cif_dir = cif_dir
        self.structural_dir = os.path.join(cif_dir, "structural", "patients")

        if narrative_version == "current":
            pointer = os.path.join(cif_dir, "narratives", "current_version.txt")
            if os.path.exists(pointer):
                with open(pointer, encoding="utf-8") as f:
                    narrative_version = f.read().strip() or _DEFAULT_NARRATIVE_VERSION_FALLBACK
            else:
                narrative_version = _DEFAULT_NARRATIVE_VERSION_FALLBACK
        self.narrative_version = narrative_version
        self.narrative_docs_dir = os.path.join(
            cif_dir, "narratives", narrative_version, "documents"
        )
        self._narrative_available = os.path.isdir(self.narrative_docs_dir)

    def iter_patients(self) -> Iterator[dict[str, Any]]:
        """Yield each patient record dict, merging narrative content in-place."""
        if not os.path.isdir(self.structural_dir):
            raise FileNotFoundError(
                f"CIF structural directory not found: {self.structural_dir}"
            )
        for filename in sorted(os.listdir(self.structural_dir)):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(self.structural_dir, filename), encoding="utf-8") as f:
                record = json.load(f)
            self._merge_narrative_into(record)
            yield record

    def _merge_narrative_into(self, record: dict[str, Any]) -> None:
        if not self._narrative_available:
            return
        enc_id = self._first_encounter_id(record)
        if not enc_id:
            return
        enc_dir = os.path.join(self.narrative_docs_dir, enc_id)
        if not os.path.isdir(enc_dir):
            return
        stub_by_id = {
            d.get("document_id", ""): d for d in (record.get("documents") or [])
        }
        for fn in sorted(os.listdir(enc_dir)):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(enc_dir, fn), encoding="utf-8") as f:
                narr_file = json.load(f)
            doc_id = narr_file.get("document_id", "")
            stub = stub_by_id.get(doc_id)
            if stub is None:
                logger.warning(
                    "CIFReader: orphan narrative file %s (document_id=%s) in "
                    "encounter %s has no matching structural stub — dropped",
                    fn, doc_id, enc_id,
                )
                continue
            stub["narrative"] = narr_file.get("narrative")

    @staticmethod
    def _first_encounter_id(record: dict[str, Any]) -> str:
        encs = record.get("encounters") or []
        if not encs:
            return ""
        return str(encs[0].get("encounter_id", ""))
