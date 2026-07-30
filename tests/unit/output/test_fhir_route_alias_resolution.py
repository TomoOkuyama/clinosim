"""Issue #458 (PR-2a): route abbreviations authored in YAML must resolve to a SNOMED coding.

`_ROUTE_SNOMED` was built to consume the tokens `parse_dose_string` emits, so its keys
are that parser's output vocabulary (`INHALED` / `NEBULIZED` / `TOPICAL` spelled out,
the rest abbreviated). YAML authors write a *third* vocabulary that was never reconciled
with it — `INH`, `NEB`, `INHALATION` — and `_ROUTE_SNOMED.get(route)` returned None for
those, so the builders emitted `{"text": "NEB"}` with no `coding`.

Measured on JP p=300 seed=42: **172 route elements** were text-only (166
MedicationAdministration + 6 MedicationRequest), all of them `NEB`.

Corroborating evidence that these are genuine route abbreviations and not typos: the
sibling JP display map `_ROUTE_JA` **already contains `INH: "吸入"`** (and `NG: "経鼻"`).
Two maps describing the same vocabulary disagreed; this aligns them for the abbreviations
that have a canonical SNOMED target already.

Design: aliases map to EXISTING `_ROUTE_SNOMED` keys. No new SNOMED code is introduced,
so the authoritative-display guard in `test_fhir_route_snomed_display.py` keeps passing
unchanged. Routes needing a *new* canonical code (`NASAL`, `NG`, `TRANSDERMAL`, the
procedure-ish ones) are deliberately NOT aliased here — they require per-code
authoritative verification.

`route.text` keeps the value the author wrote (`NEB` stays `NEB`, not normalised to
`NEBULIZED`): `CodeableConcept.text` is the place for the source system's own wording
while `coding` carries the standard meaning.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output._fhir_common import _build_dosage_instruction, build_route_concept
from clinosim.modules.output._fhir_localization import _ROUTE_JA
from clinosim.modules.output._fhir_reference_data import _ROUTE_ALIASES, _ROUTE_SNOMED

pytestmark = pytest.mark.unit

_SNOMED_URI = "http://snomed.info/sct"
_RESPIRATORY = "447694001"


# ---------------------------------------------------------------- alias table integrity


def test_every_alias_targets_an_existing_canonical_key():
    """Aliases must point at `_ROUTE_SNOMED` keys — a typo'd target resolves to nothing.

    Without this, `_ROUTE_ALIASES = {"NEB": "NEBULISED"}` (British spelling typo) would
    silently keep emitting text-only routes: exactly the defect being fixed.
    """
    bad = {a: t for a, t in _ROUTE_ALIASES.items() if t not in _ROUTE_SNOMED}
    assert bad == {}, f"aliases whose target is not a _ROUTE_SNOMED key: {bad}"


def test_no_alias_shadows_a_canonical_key():
    """An alias that is also a canonical key would be ambiguous — forbid the overlap."""
    overlap = set(_ROUTE_ALIASES) & set(_ROUTE_SNOMED)
    assert overlap == set(), f"alias keys that are also canonical keys: {sorted(overlap)}"


def test_alias_keys_are_uppercase():
    """Lookup happens after `.upper()`, so a lower-case alias key is dead weight."""
    assert all(a == a.upper() for a in _ROUTE_ALIASES), sorted(_ROUTE_ALIASES)


def test_canonical_set_is_unchanged_by_this_pr():
    """No new SNOMED code is introduced — only aliases onto existing entries.

    Pins the reason `test_fhir_route_snomed_display.py` (which parametrizes over
    `_ROUTE_SNOMED` and demands an authoritative display per code) is unaffected.
    """
    assert set(_ROUTE_SNOMED) == {
        "PO",
        "IV",
        "SC",
        "IM",
        "SL",
        "PR",
        "INHALED",
        "NEBULIZED",
        "TOPICAL",
    }


def test_alias_table_covers_the_measured_offenders():
    """The three YAML-authored abbreviations found by the session-74 sweep."""
    assert set(_ROUTE_ALIASES) == {"INH", "INHALATION", "NEB"}


def test_inh_is_already_a_recognised_abbreviation_in_the_ja_map():
    """Corroboration, not a new claim: `_ROUTE_JA` already treats INH as a route.

    If this stops holding, the premise of the alias (INH is a real abbreviation this
    codebase already understands, not a typo) has changed and should be re-argued.
    """
    assert _ROUTE_JA.get("INH") == "吸入"


# ---------------------------------------------------------------- build_route_concept


@pytest.mark.parametrize("raw", ["INH", "inh", "Inh", "INHALATION", "NEB", "neb"])
def test_aliased_routes_now_emit_a_coding(raw):
    concept = build_route_concept(raw)
    assert concept is not None
    assert concept["coding"] == [
        {
            "system": _SNOMED_URI,
            "code": _RESPIRATORY,
            "display": "Respiratory tract route (qualifier value)",
        }
    ]


@pytest.mark.parametrize("raw", ["INH", "inh", "NEB", "neb", "INHALATION"])
def test_route_text_preserves_the_authored_value_uppercased(raw):
    """`text` is the author's wording (upper-cased), NOT the canonical key.

    `NEB` must stay `NEB` — normalising it to `NEBULIZED` would write a string the
    source data never contained.
    """
    assert build_route_concept(raw)["text"] == raw.upper()


@pytest.mark.parametrize(
    "raw,code",
    [
        ("PO", "26643006"),
        ("IV", "47625008"),
        ("SC", "34206005"),
        ("IM", "78421000"),
        ("SL", "37839007"),
        ("PR", "37161004"),
        ("TOPICAL", "6064005"),
        ("INHALED", _RESPIRATORY),
        ("NEBULIZED", _RESPIRATORY),
    ],
)
def test_canonical_routes_unchanged(raw, code):
    """Every pre-existing canonical route resolves exactly as before."""
    concept = build_route_concept(raw)
    assert concept["coding"][0]["code"] == code
    assert concept["text"] == raw


@pytest.mark.parametrize("raw", ["CATHETER", "PROCEDURAL", "EXTRACORPOREAL", "NASAL", "NG", "N/A"])
def test_unresolvable_routes_stay_text_only(raw):
    """Routes without a verified canonical code keep the honest text-only form.

    These need a NEW SNOMED code, which requires per-code authoritative verification —
    aliasing them onto an existing code would be a silent code substitution. `NG` is
    listed here on purpose: `parse_dose_string` can emit it and `_ROUTE_JA` translates
    it, but `_ROUTE_SNOMED` has no entry, so it must not be guessed at.
    """
    concept = build_route_concept(raw)
    assert concept == {"text": raw}
    assert "coding" not in concept


@pytest.mark.parametrize("raw", ["", None])
def test_absent_route_yields_no_concept(raw):
    """Empty means unknown — emit no route element rather than an empty CodeableConcept."""
    assert build_route_concept(raw) is None


def test_helper_internalises_the_uppercase_normalisation():
    """Call sites must not need their own `.upper()`; double-applying it is harmless
    but the helper owning it is what makes the two call sites identical."""
    assert build_route_concept("neb") == build_route_concept("NEB")


# ---------------------------------------------------------------- call-site wiring


def test_dosage_instruction_emits_coding_for_aliased_route():
    """`_build_dosage_instruction` (MedicationRequest path) goes through the helper."""
    dosage = _build_dosage_instruction(
        {"route": "NEB", "dose_quantity": 2.5, "dose_unit": "mg", "frequency": "DAILY"},
        country="US",
    )
    assert dosage is not None
    assert dosage["route"]["coding"][0]["code"] == _RESPIRATORY
    assert dosage["route"]["text"] == "NEB"


def test_dosage_instruction_text_still_uses_the_authored_token():
    """The human-readable summary keeps using the authored token, so `dosage.text`
    is byte-unchanged by this PR (the JP path already translates NEB separately)."""
    dosage = _build_dosage_instruction(
        {"route": "NEB", "dose_quantity": 2.5, "dose_unit": "mg"},
        country="US",
    )
    assert "NEB" in dosage["text"]


def test_medication_admin_emits_coding_for_aliased_route():
    """`_build_medication_admin` (MedicationAdministration path) goes through the helper.

    This is the path that produced 166 of the 172 measured text-only elements, so the
    MR-only test above would not have caught a half-applied fix.
    """
    from clinosim.modules.output._fhir_medications import _build_medication_admin

    resource = _build_medication_admin(
        {"drug_name": "Salbutamol", "dose": "2.5mg", "route": "NEB", "status": "given"},
        patient_id="POP-000001",
        index=1,
        country="US",
        encounter_id="ENC-POP-000001-000000000001",
    )
    assert resource["dosage"]["route"]["coding"][0]["code"] == _RESPIRATORY
    assert resource["dosage"]["route"]["text"] == "NEB"


def test_medication_admin_unresolvable_route_stays_text_only():
    from clinosim.modules.output._fhir_medications import _build_medication_admin

    resource = _build_medication_admin(
        {"drug_name": "Urokinase", "dose": "60000 IU", "route": "CATHETER", "status": "given"},
        patient_id="POP-000001",
        index=2,
        country="US",
        encounter_id="ENC-POP-000001-000000000001",
    )
    assert resource["dosage"]["route"] == {"text": "CATHETER"}


def test_both_call_sites_produce_identical_concepts_for_the_same_route():
    """The point of consolidating: MR and MAR must not drift apart again."""
    from clinosim.modules.output._fhir_medications import _build_medication_admin

    mr_dosage = _build_dosage_instruction({"route": "NEB", "dose_quantity": 2.5, "dose_unit": "mg"}, country="US")
    mar = _build_medication_admin(
        {"drug_name": "Salbutamol", "dose": "2.5mg", "route": "NEB", "status": "given"},
        patient_id="POP-000001",
        index=1,
        country="US",
        encounter_id="ENC-POP-000001-000000000001",
    )
    assert mr_dosage["route"] == mar["dosage"]["route"]


def _route_map_references(path):
    """Function names containing a code reference to `_ROUTE_SNOMED` / `_ROUTE_ALIASES`.

    AST-based, so prose in docstrings and comments is ignored — a string `count()` would
    make this guard fire on documentation and is not what "the lookup lives in one
    place" means. Returns `"<module>"` for references outside any function.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    parent_func = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for child in ast.walk(node):
                parent_func.setdefault(id(child), node.name)
    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in ("_ROUTE_SNOMED", "_ROUTE_ALIASES"):
            hits.add(parent_func.get(id(node), "<module>"))
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in ("_ROUTE_SNOMED", "_ROUTE_ALIASES"):
                    hits.add("<import>")
    return hits


def test_no_builder_reads_the_route_maps_directly():
    """The route maps must not be looked up outside `build_route_concept`.

    Two independent `_ROUTE_SNOMED.get(...)` sites drifting apart is what allowed the
    MAR path to accumulate 166 of the 172 defects while the MR path had 6. The single
    helper is the fix; this test keeps it single. `_fhir_reference_data` (the definition)
    and `fhir_r4_adapter` (a `# noqa: F401` backwards-compat re-export) are exempt.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "output"
    exempt = {"_fhir_reference_data.py", "fhir_r4_adapter.py", "_fhir_common.py"}
    offenders = {}
    for path in sorted(root.glob("*.py")):
        if path.name in exempt:
            continue
        refs = _route_map_references(path) - {"<import>"}
        if refs:
            offenders[path.name] = sorted(refs)
    assert offenders == {}, (
        f"these builders reference the route maps directly instead of calling build_route_concept(): {offenders}"
    )


def test_common_module_confines_the_lookup_to_the_helper():
    """`_fhir_common` owns the maps' only lookup — it must sit in `build_route_concept`."""
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "output" / "_fhir_common.py"
    refs = _route_map_references(path) - {"<import>"}
    assert refs == {"build_route_concept"}, (
        f"route-map lookups in _fhir_common.py live in {sorted(refs)}; they belong only in build_route_concept()"
    )
