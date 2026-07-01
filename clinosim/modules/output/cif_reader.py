"""CIFReader — Two-pass CIF merge loader (AD-65 Task 4).

All FHIR / CSV adapters read patient records via this reader instead of
walking ``structural/patients/*.json`` directly. Narrative content written by
a NarrativePass (``cif/narratives/<version>/documents/<enc>/<doc_id>.json``,
Task 3) is merged into the matching structural stub's ``narrative`` field at
read time, so downstream builders always see the two-layer CIF as a single
merged dict tree (spec §"CIF file layout on disk (two-layer)").

Merge semantics:
  - Missing per-encounter narrative directory (no documents were generated
    for that encounter, or the pass hasn't run yet for this encounter) →
    no-op merge (stubs retain ``narrative=None``).
  - Narrative file whose ``document_id`` has no matching structural stub
    (orphan — e.g. stale narrative version pointing at a doc since removed
    from a disease/encounter YAML) → warn + drop (never invent a stub).

``narrative_version="current"`` resolves via the ``current_version.txt``
pointer file (``cif/narratives/current_version.txt``); if the pointer is
missing, it falls back to ``"template"`` (the Stage 2 default writer,
Task 3). If the resolved directory (explicit or fallback) does not exist,
``__init__`` **raises FileNotFoundError** rather than silently emitting
without narrative content (F-1 adv-1 fix — a typo in the CLI
``--narrative-version`` arg previously produced empty DocumentReference /
Composition output with no error signal).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_NARRATIVE_VERSION_FALLBACK = "template"


def resolve_current_narrative_dir(cif_dir: str) -> str:
    """Resolve ``<cif_dir>/narratives/<version>/documents`` for the "current" alias.

    Reads the ``narratives/current_version.txt`` pointer file to determine which
    version to load; falls back to ``"template"`` when the pointer is missing
    (backward-compat with cohorts generated before pointer support). This helper
    is a **backward-compat resolver only** — it does NOT raise when the
    resolved narrative directory does not exist (a legitimate use case for
    audit walks over a cohort still in the pre-narrate state). Callers that
    require the directory to exist (e.g. ``CIFReader``) must check explicitly.

    F-3 adv-1 fix: shared between ``CIFReader`` and ``document/audit.py`` (4
    call sites) to unify the pointer-resolution path.
    """
    pointer = os.path.join(cif_dir, "narratives", "current_version.txt")
    if os.path.exists(pointer):
        with open(pointer, encoding="utf-8") as f:
            version = f.read().strip() or _DEFAULT_NARRATIVE_VERSION_FALLBACK
    else:
        version = _DEFAULT_NARRATIVE_VERSION_FALLBACK
    return os.path.join(cif_dir, "narratives", version, "documents")


class CIFReader:
    """Single load path for two-layer CIF (structural + narrative)."""

    def __init__(self, cif_dir: str, narrative_version: str = "current"):
        self.cif_dir = cif_dir
        self.structural_dir = os.path.join(cif_dir, "structural", "patients")

        # 明示 version 指定は resolve 前に validation する必要がある(F-1 fix)
        explicit_version = narrative_version != "current"

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

        # F-1 fix: 明示指定された version が見つからない場合は raise。
        # "current" 経由(pointer missing → template fallback)でも解決先が
        # 存在しない場合は同じく raise — silent-no-op(空 DocumentReference /
        # Composition 排出)を防ぐ。CLI ``--narrative-version`` typo が
        # xhigh review で silent-no-op を作っていた root cause。
        if not self._narrative_available:
            if explicit_version:
                raise FileNotFoundError(
                    f"CIFReader: narrative version {narrative_version!r} not "
                    f"found under {cif_dir}/narratives/ — check the "
                    f"--narrative-version arg or run `clinosim narrate` first"
                )
            raise FileNotFoundError(
                f"CIFReader: narrative directory {self.narrative_docs_dir} "
                f"not found (no current_version.txt pointer and no fallback "
                f"'{_DEFAULT_NARRATIVE_VERSION_FALLBACK}' dir) — run "
                "`clinosim narrate` before exporting"
            )

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
