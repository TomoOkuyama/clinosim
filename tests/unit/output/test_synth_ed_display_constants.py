"""Lock the synth-ED display constants (Issue #546 partial).

The 4 display strings that used to be inlined at 4 sites in
`_fhir_inline_bb.py::_bb_encounters` are now centralised in
`_SYNTH_ED_DISPLAYS`. These tests lock:

1. The exact JP + US values (a rename or accidental drop is caught).
2. `_synth_ed_display(slot, country)` gates on the canonical `is_jp()`
   helper (whitespace-safe, matches the AGENTS.md `is_jp(country)` rule).
3. All 4 slots are covered — no dead entry / missing entry.
4. Bare `"救急外来"`, `"緊急"`, `"外来より"`, `"入院となる"` literals do not
   reappear in `_fhir_inline_bb.py` outside `_SYNTH_ED_DISPLAYS` (AST-level
   guard against future inline drift).
"""

from __future__ import annotations

import ast
from pathlib import Path

from clinosim.modules.output.fhir_r4.lib.inline_bb import _SYNTH_ED_DISPLAYS, _synth_ed_display

EXPECTED_SLOTS: dict[str, tuple[str, str]] = {
    "class_emer": ("救急外来", "Emergency"),
    "priority_em": ("緊急", "emergency"),
    "admit_source_outp": ("外来より", "From outpatient"),
    "discharge_disposition_hosp": ("入院となる", "Admitted to hospital"),
}


def test_synth_ed_displays_exact_values() -> None:
    assert _SYNTH_ED_DISPLAYS == EXPECTED_SLOTS


def test_synth_ed_display_jp_gate() -> None:
    for slot, (jp, en) in EXPECTED_SLOTS.items():
        assert _synth_ed_display(slot, "JP") == jp
        assert _synth_ed_display(slot, "US") == en


def test_synth_ed_display_unknown_country_defaults_to_us() -> None:
    """Default-US convention: unknown country codes render the US display."""
    for slot, (_, en) in EXPECTED_SLOTS.items():
        assert _synth_ed_display(slot, "XX") == en


def test_synth_ed_display_all_slots_have_two_values() -> None:
    for slot, pair in _SYNTH_ED_DISPLAYS.items():
        assert isinstance(pair, tuple) and len(pair) == 2, f"{slot!r} must be a (JP, US) tuple"
        assert pair[0] and pair[1], f"{slot!r} JP and US must both be non-empty"


def test_no_bare_synth_ed_literals_in_inline_bb_source() -> None:
    """Guard against inline drift: the 4 hardcoded literals must appear
    ONLY as values inside the `_SYNTH_ED_DISPLAYS` dict — anywhere else in
    the source is a regression to the pre-Issue #546 pattern.
    """
    src = (Path(__file__).parent / "../../../clinosim/modules/output/fhir_r4/lib/inline_bb.py").resolve().read_text()
    tree = ast.parse(src)

    forbidden = {"救急外来", "緊急", "外来より", "入院となる"}
    # Collect the string constants that are values of the `_SYNTH_ED_DISPLAYS`
    # dict assignment — those are the ALLOWED occurrences. Everything else
    # is a regression.
    allowed_nodes: set[int] = set()
    for node in ast.walk(tree):
        target_name = None
        value_node = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value_node = node.value
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    target_name = t.id
                    value_node = node.value
                    break
        if target_name == "_SYNTH_ED_DISPLAYS" and value_node is not None:
            for child in ast.walk(value_node):
                if isinstance(child, ast.Constant):
                    allowed_nodes.add(id(child))

    violations = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value in forbidden and id(node) not in allowed_nodes
    ]
    assert not violations, (
        f"Bare synth-ED display literals outside _SYNTH_ED_DISPLAYS: "
        f"{violations}. Use _synth_ed_display(slot, country) instead."
    )
