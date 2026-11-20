"""Issue #3390 — one chief complaint per encounter.

Every section of a document reads the complaint through
``encounter_chief_complaint``; the ROS filter checks both the displayed
complaint and the encounter's recorded one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative.renderers.section_builders import hpi
from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import build_assessment_and_plan
from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import (
    build_chief_complaint,
    chief_complaint_texts,
    encounter_chief_complaint,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType
from tests.unit.modules.document.narrative.test_chief_complaint_variant_compat_3275 import _ctx

_GEN = TemplateNarrativeGenerator()
_RAW = load_disease_protocol("urinary_tract_infection").chief_complaint["ja"]
_ROOT = Path(__file__).resolve().parents[5] / "clinosim/modules/document/narrative/renderers"


def _swapped_ctx() -> tuple[object, str]:
    """An elderly UTI encounter whose displayed complaint is a variant."""
    for n in range(200):
        ctx = _ctx("urinary_tract_infection", age=84, cc_ja=_RAW, n=n)
        shown = encounter_chief_complaint(ctx)
        if shown != _RAW:
            return ctx, shown
    pytest.fail("no variant picked")


def test_every_section_cites_the_same_complaint() -> None:
    ctx, shown = _swapped_ctx()
    assert build_chief_complaint(_GEN, ctx)[0] == shown  # type: ignore[arg-type]
    ap, _ = build_assessment_and_plan(_GEN, ctx)  # type: ignore[arg-type]
    assert shown in ap
    assert _RAW not in ap

    from clinosim.modules.document.narrative.renderers._ed_helpers import ed_disposition_reason

    assert ed_disposition_reason(ctx, "ja") == shown  # type: ignore[arg-type]
    ctx.document_type = DocumentType.DISCHARGE_SUMMARY  # type: ignore[attr-defined]


def test_ros_does_not_deny_a_symptom_of_the_recorded_complaint() -> None:
    ctx, shown = _swapped_ctx()
    assert "側腹部痛" not in shown
    assert chief_complaint_texts(ctx) == (shown, _RAW)  # type: ignore[arg-type]
    ros = hpi._ros_line(ctx, shown)  # type: ignore[arg-type]
    for word in ("発熱", "排尿時痛", "側腹部痛"):
        assert f"{word}なし" not in ros


def test_en_locale_has_no_swap() -> None:
    ctx = _ctx("urinary_tract_infection", age=84, cc_ja=_RAW, n=1)
    ctx.target_lang = "en"
    ctx.encounter.chief_complaint = "Fever, dysuria"
    assert encounter_chief_complaint(ctx) == "Fever, dysuria"
    assert chief_complaint_texts(ctx) == ("Fever, dysuria",)


def test_no_section_builder_reads_the_complaint_slots_directly() -> None:
    # The resolver itself, the HPI (reads the localized slot, then displays it
    # through the resolver's swap), and the two keyword-matching readers of
    # _composers (pain site, exam wording), which need the recorded complaint.
    allowed = {"section_builders/chief_complaint.py", "section_builders/hpi.py", "_composers.py"}
    hits = []
    for path in _ROOT.rglob("*.py"):
        rel = path.relative_to(_ROOT).as_posix()
        if rel in allowed:
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"(_o|getattr|localized_field)\((?:ctx\.)?(enc|encounter)\b[^)]*chief_complaint", line):
                hits.append(f"{rel}:{i}: {line.strip()}")
    assert not hits, hits
