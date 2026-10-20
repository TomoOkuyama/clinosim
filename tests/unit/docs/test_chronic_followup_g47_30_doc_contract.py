"""Phase 4d — chronic_followup.yaml G47.30 header doc contract pin.

Carry-forward from Phase 4b.1's doc-contract discipline (concept:
grep-based-doc-contract-test-for-stale-yaml-comments). The G47.30 block
header must not claim behavior that Phase 4d does not ship.
"""

from __future__ import annotations

from pathlib import Path

YAML = Path(__file__).resolve().parents[3] / "clinosim" / "locale" / "shared" / "chronic_followup.yaml"


def _extract_g47_30_block(text: str) -> str:
    """Return just the G47.30 block section (header + fields) for scoped grep."""
    lines = text.splitlines()
    out: list[str] = []
    in_block = False
    for line in lines:
        if line.startswith("G47.30:"):
            in_block = True
        elif in_block and line and not line.startswith((" ", "\t", "#")):
            # Next top-level key reached — stop.
            break
        if in_block:
            out.append(line)
    return "\n".join(out)


def test_g47_30_header_doc_does_not_claim_unimplemented_behavior():
    """Phase 4d ships CPAP (every_visit) + polysomnography (baseline_only)
    on exact G47.30 chronic_followup. Phrases implying features NOT
    shipped must not appear in the block header."""
    text = YAML.read_text(encoding="utf-8")
    block = _extract_g47_30_block(text)
    assert block, "G47.30 block not found"
    forbidden = (
        "DeviceRequest",  # Phase 4d uses Procedure, not DeviceRequest
        "AHI severity gate",  # no severity gate shipped
        "BiPAP alternative",  # only CPAP shipped
        "annual re-titration",  # polysomnography is baseline_only in 4d
    )
    hits = [p for p in forbidden if p in block]
    assert not hits, f"chronic_followup.yaml G47.30 block claims unimplemented Phase 4d behavior: {hits}"
