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
pointer file (``cif/narratives/current_version.txt``). Silent-no-op defense
(F-1 adv-1 fix — a typo in the CLI ``--narrative-version`` arg previously
produced empty DocumentReference / Composition output with no error signal)
follows a 3-case policy in ``__init__``:

1. Explicit ``narrative_version != "current"`` → resolved directory MUST
   exist; raises ``FileNotFoundError`` otherwise.
2. ``narrative_version="current"`` with pointer file present → the pointed
   version MUST exist; raises ``FileNotFoundError`` otherwise.
3. ``narrative_version="current"`` with pointer file absent AND no
   fallback ``"template"`` directory → structural-only mode: warn + continue
   (``_narrative_available=False``). Downstream FHIR builders emit
   structural-only output cleanly; typo protection is not needed here
   because there is no user-supplied version to typo.
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

        # F-1 fix: 3 cases for the resolved narrative_version → raise policy:
        # 1. Explicit version (not "current"): user requested a specific version;
        #    if its dir is missing, raise (typo in --narrative-version = xhigh
        #    silent-no-op root cause).
        # 2. "current" alias with pointer file: pointer says "version X"; if X's
        #    dir missing, raise (broken generate/narrate flow).
        # 3. "current" alias without pointer: fall back to "template"; if template
        #    dir also missing, this is a legitimate "structural-only CIF" case
        #    (e.g. a test fixture, or a pre-narrate export step) — log a warning
        #    and continue with `_narrative_available=False`. Silent no-op merge
        #    is acceptable here because the user did NOT request a specific
        #    version; they get whatever is there.
        explicit_version = narrative_version != "current"
        pointer_used = False

        if narrative_version == "current":
            pointer = os.path.join(cif_dir, "narratives", "current_version.txt")
            if os.path.exists(pointer):
                with open(pointer, encoding="utf-8") as f:
                    narrative_version = f.read().strip() or _DEFAULT_NARRATIVE_VERSION_FALLBACK
                pointer_used = True
            else:
                narrative_version = _DEFAULT_NARRATIVE_VERSION_FALLBACK
        self.narrative_version = narrative_version
        self.narrative_docs_dir = os.path.join(cif_dir, "narratives", narrative_version, "documents")
        self._narrative_available = os.path.isdir(self.narrative_docs_dir)

        if not self._narrative_available:
            if explicit_version or pointer_used:
                raise FileNotFoundError(
                    f"CIFReader: narrative version {narrative_version!r} not "
                    f"found under {cif_dir}/narratives/ — check the "
                    f"--narrative-version arg or run `clinosim narrate` first"
                )
            # Case 3: no pointer, fallback dir also missing → structural-only
            # mode. Log a warning so the user sees this is not a silent no-op,
            # but don't raise (backward-compat with pre-AD-65 structural CIF).
            logger.warning(
                "CIFReader: no narrative directory found under %s/narratives/ — "
                "structural-only mode (documents will retain narrative=None). "
                "Run `clinosim narrate` if narrative content is expected.",
                cif_dir,
            )

    def iter_patients(self) -> Iterator[dict[str, Any]]:
        """Yield each patient record dict, merging narrative content in-place."""
        if not os.path.isdir(self.structural_dir):
            raise FileNotFoundError(f"CIF structural directory not found: {self.structural_dir}")
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
        stub_by_id = {d.get("document_id", ""): d for d in (record.get("documents") or [])}
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
                    fn,
                    doc_id,
                    enc_id,
                )
                continue
            stub["narrative"] = narr_file.get("narrative")

    @staticmethod
    def _first_encounter_id(record: dict[str, Any]) -> str:
        encs = record.get("encounters") or []
        if not encs:
            return ""
        return str(encs[0].get("encounter_id", ""))
