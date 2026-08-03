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


def test_inh_alias_resolves_to_the_canonical_ja_entry():
    """Corroboration, not a new claim: `INH` resolves to a canonical `_ROUTE_JA` entry.

    Historical shape (before Issue #479 dual-slot fix): `_ROUTE_JA["INH"] = "吸入"`
    (alias key). That has been consolidated — `_ROUTE_JA` now holds ONLY canonical keys
    (invariant test_route_ja_contains_no_alias_keys), and `build_route_concept`
    resolves alias → canonical BEFORE the JA lookup, so `INH` still translates through
    the canonical entry `INHALED`. If this stops holding, the premise of the alias
    (INH is a real abbreviation this codebase already understands, not a typo) has
    changed and should be re-argued.
    """
    assert _ROUTE_ALIASES["INH"] == "INHALED"
    assert _ROUTE_JA["INHALED"] == "吸入"


# ---------------------------------------------------------------- build_route_concept


@pytest.mark.parametrize("raw", ["INH", "inh", "Inh", "INHALATION", "NEB", "neb"])
def test_aliased_routes_now_emit_a_coding(raw):
    concept = build_route_concept(raw, "US")
    assert concept is not None
    assert concept["coding"] == [
        {
            "system": _SNOMED_URI,
            "code": _RESPIRATORY,
            "display": "Respiratory tract route (qualifier value)",
        }
    ]


@pytest.mark.parametrize("raw", ["INH", "inh", "NEB", "neb", "INHALATION"])
def test_route_text_preserves_the_authored_value_uppercased_on_us(raw):
    """US: `text` is the author's wording (upper-cased), NOT the canonical key.

    `NEB` must stay `NEB` — normalising it to `NEBULIZED` would write a string the
    source data never contained. JP output localizes instead (see
    `test_route_text_localizes_to_ja_on_jp`).
    """
    assert build_route_concept(raw, "US")["text"] == raw.upper()


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
    concept = build_route_concept(raw, "US")
    assert concept["coding"][0]["code"] == code
    assert concept["text"] == raw


@pytest.mark.parametrize("raw", ["CATHETER", "PROCEDURAL", "EXTRACORPOREAL", "NASAL", "N/A"])
def test_unresolvable_routes_stay_text_only(raw):
    """Routes without a verified canonical code keep the honest text-only form.

    These need a NEW SNOMED code, which requires per-code authoritative verification —
    aliasing them onto an existing code would be a silent code substitution. `NG` is
    tested separately (`test_ng_fallback_localizes_ja_even_without_snomed`) because it
    has a JA translation and Issue #479 makes fallback text follow the same dual-slot
    rule: coding is absent, but text is localized for JP.
    """
    concept = build_route_concept(raw, "US")
    assert concept == {"text": raw}
    assert "coding" not in concept


@pytest.mark.parametrize("raw", ["", None])
def test_absent_route_yields_no_concept(raw):
    """Empty means unknown — emit no route element rather than an empty CodeableConcept."""
    assert build_route_concept(raw, "US") is None


def test_helper_internalises_the_uppercase_normalisation():
    """Call sites must not need their own `.upper()`; double-applying it is harmless
    but the helper owning it is what makes the two call sites identical."""
    assert build_route_concept("neb", "US") == build_route_concept("NEB", "US")


def test_country_is_required():
    """`country` has no default. Every call site MUST forward it explicitly — a
    missing forward is a silent locale drift (`_build_dosage_instruction` shipped
    with `build_route_concept(...)` missing `country` in PR #484; JP output silently
    emitted the US text form). `TypeError` at call time > silent drift.
    """
    with pytest.raises(TypeError):
        build_route_concept("PO")  # type: ignore[call-arg]


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
    """`_fhir_common` owns the maps' only lookup — three sanctioned functions:
    `build_route_concept` (the CodeableConcept builder), `canonicalize_route` (the
    alias-aware normalizer for downstream gates like `_is_infusion`), and
    `_validate_route_maps` (the import-time reverse-coverage guard).

    All three live in `_fhir_common.py` so downstream builders import a function,
    never the underlying `_ROUTE_*` dicts (test_no_builder_reads_the_route_maps_directly).
    """
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "output" / "_fhir_common.py"
    refs = _route_map_references(path) - {"<import>"}
    assert refs == {"build_route_concept", "canonicalize_route", "_validate_route_maps"}, (
        f"route-map lookups in _fhir_common.py live in {sorted(refs)}; they belong only in "
        f"build_route_concept() / canonicalize_route() / _validate_route_maps()"
    )


# ---------------------------------------------------------------- Issue #479: JP dual-slot


@pytest.mark.parametrize(
    "raw,ja",
    [
        ("PO", "経口"),
        ("IV", "静注"),
        ("SC", "皮下注"),
        ("IM", "筋注"),
        ("SL", "舌下"),
        ("PR", "直腸"),
        ("TOPICAL", "外用"),
        ("INHALED", "吸入"),
        ("NEBULIZED", "ネブライザー"),
    ],
)
def test_route_text_localizes_to_ja_on_jp_canonical(raw, ja):
    """JP output: `text` is the JA translation, `coding.display` stays English (dual-slot).

    Dual-slot rule (Issue #479): `CodeableConcept.text` is the user-facing string and
    MUST be localized; `coding.display` is the CodeSystem-canonical English and MUST
    stay English. Same shape as Observation.code / Procedure.code emit.
    """
    concept = build_route_concept(raw, "JP")
    assert concept is not None
    assert concept["text"] == ja, f"text should be localized JA for {raw}"
    assert concept["coding"][0]["display"] not in (ja, ""), (
        "coding.display must remain the English canonical (SNOMED authoritative), not JA"
    )


@pytest.mark.parametrize(
    "raw,ja",
    [
        ("INH", "吸入"),
        ("INHALATION", "吸入"),
        ("NEB", "ネブライザー"),
        ("inh", "吸入"),
        ("neb", "ネブライザー"),
    ],
)
def test_route_text_localizes_via_canonical_for_aliases(raw, ja):
    """Alias resolution runs BEFORE the JA lookup.

    Historical bug (PR #484 pre-fix): `_ROUTE_JA.get(raw, raw)` used the raw form,
    so `INHALATION` (alias) hit `_ROUTE_JA.get("INHALATION", ...)` → not present →
    English `"INHALATION"` in JP output. Resolving alias → canonical first (`INHALATION`
    → `INHALED` → `吸入`) closes this gap and makes the JA table smaller (canonical only,
    no per-alias duplicates).
    """
    concept = build_route_concept(raw, "JP")
    assert concept is not None
    assert concept["text"] == ja


def test_ng_fallback_localizes_ja_even_without_snomed():
    """SNOMED-less routes with a JA entry get localized `text` (fallback path, Issue #479).

    `NG` (nasogastric) has a `_ROUTE_JA` entry `"経鼻"` but no `_ROUTE_SNOMED` entry
    (the code needs authoritative verification against a terminology server). The dual-slot
    rule says `text` is the user-facing string regardless of whether `coding` was
    populated. JP output MUST emit `"経鼻"`, not the English abbreviation.
    """
    concept = build_route_concept("NG", "JP")
    assert concept == {"text": "経鼻"}
    assert "coding" not in concept


def test_unknown_route_stays_english_even_on_jp():
    """A route absent from both `_ROUTE_SNOMED` and `_ROUTE_JA` gets no fake translation.

    Better to emit the raw string than to invent a translation the author never wrote.
    An operator seeing `"CATHETER"` in JP output can trace it back; a mistranslated
    `カテーテル` (guessed) hides the fact that JA coverage is incomplete.
    """
    concept = build_route_concept("CATHETER", "JP")
    assert concept == {"text": "CATHETER"}


# ------------------------------------------------------- Issue #479: _ROUTE_JA invariants


def test_route_ja_covers_every_canonical_snomed_key():
    """A new `_ROUTE_SNOMED` canonical entry MUST have a companion `_ROUTE_JA` entry.

    Without this guard, adding a canonical route without JA coverage would silently
    emit the English canonical on JP output (dual-slot violation). Enforced at import
    time by `_validate_route_maps()`; this test pins the current SNOMED-canonical set
    as fully covered.
    """
    missing = set(_ROUTE_SNOMED.keys()) - set(_ROUTE_JA.keys())
    assert missing == set(), f"_ROUTE_JA missing JP translation for canonical SNOMED routes: {sorted(missing)}"


def test_route_ja_contains_no_alias_keys():
    """`_ROUTE_JA` MUST NOT contain `_ROUTE_ALIASES` keys.

    Aliases are resolved to canonical BEFORE the JA lookup, so an alias entry in
    `_ROUTE_JA` is dead code (never reached) and misleads authors into thinking
    coverage exists. Enforced at import time by `_validate_route_maps()`.
    """
    overlap = set(_ROUTE_JA.keys()) & set(_ROUTE_ALIASES.keys())
    assert overlap == set(), (
        f"_ROUTE_JA contains alias keys — resolve via _ROUTE_ALIASES to canonical first: {sorted(overlap)}"
    )


def test_import_time_guard_rejects_alias_key_in_route_ja():
    """`_validate_route_maps` must raise when an alias key sneaks into `_ROUTE_JA`.

    Smoke test: mutate a copy of `_ROUTE_JA` to include an alias key, re-run the
    guard, expect `ValueError`. Direct call because monkeypatching the module-global
    on import is fragile (the guard runs at import, before test fixtures).
    """
    from clinosim.modules.output._fhir_common import _validate_route_maps

    # Temporarily poison _ROUTE_JA and confirm the guard rejects.
    _ROUTE_JA["INH"] = "吸入"  # alias key sneaking in
    try:
        with pytest.raises(ValueError, match="alias keys"):
            _validate_route_maps()
    finally:
        del _ROUTE_JA["INH"]


def test_import_time_guard_rejects_missing_canonical_in_route_ja():
    """`_validate_route_maps` must raise when a canonical `_ROUTE_SNOMED` key lacks
    a `_ROUTE_JA` entry — the class of bug that silently emits English on JP output.
    """
    from clinosim.modules.output._fhir_common import _validate_route_maps

    saved = _ROUTE_JA.pop("PO")
    try:
        with pytest.raises(ValueError, match="missing JP translation"):
            _validate_route_maps()
    finally:
        _ROUTE_JA["PO"] = saved


# ---------- Issue #479 downstream: _is_infusion gate uses canonical, not text_value


def test_iv_continuous_infusion_still_emits_device_on_jp():
    """Silent-no-op regression guard: JP output MUST NOT lose the infusion-pump `device`
    reference on IV continuous infusions.

    `_build_medication_admin` gates `resource["device"]` on the route being IV. Before
    Issue #479 the gate compared `route_concept["text"] == "IV"`; localizing `text` to
    `"静注"` on JP would flip every IV MAR to `route == "IV"` False and drop the device
    reference silently. Same J5 class as PR #475 (`dose_text.upper()` losing `rateQuantity`
    on 488 rows). The fix routes the gate through `canonicalize_route()` so it compares
    the canonical `IV`, unaffected by dual-slot localization.
    """
    from clinosim.modules.output._fhir_medications import _build_medication_admin

    resource = _build_medication_admin(
        {
            "drug_name": "Norepinephrine",
            "dose": "0.1 mcg/kg/min CONTINUOUS",
            "route": "IV",
            "status": "given",
        },
        patient_id="POP-000001",
        index=1,
        country="JP",
        encounter_id="ENC-POP-000001-000000000001",
    )
    # dosage.route.text localized (dual-slot)
    assert resource["dosage"]["route"]["text"] == "静注", "route.text must be JA on JP"
    # device reference MUST still be emitted (the silent-no-op case)
    assert "device" in resource, (
        "IV continuous infusion on JP must still emit device[] (infusion-pump ref); "
        "if this drops, the _is_infusion gate is comparing localized text again"
    )


def test_infusion_gate_survives_future_iv_alias():
    """Future-proof guard: adding an alias for IV (e.g. `INTRAVENOUS`) MUST NOT
    silently drop the infusion-pump `device[]` reference.

    Motivating scenario: someone adds `_ROUTE_ALIASES["INTRAVENOUS"] = "IV"` to cover
    a YAML that writes it out in full. Before this PR the gate compared
    `mar.get("route").upper() == "IV"` — that comparison is `"INTRAVENOUS" == "IV"`,
    False, and every INTRAVENOUS continuous infusion silently loses `resource["device"]`.
    Same J5 class the rest of this PR is fixing (the "raw vs canonical" mistake).

    The fix routes the gate through `canonicalize_route()`, which resolves the alias
    to the canonical `IV` first — so this test uses `monkeypatch.setitem` to inject
    an IV alias and verifies `device[]` still emits.
    """
    from clinosim.modules.output import _fhir_reference_data
    from clinosim.modules.output._fhir_medications import _build_medication_admin

    # Inject a hypothetical IV alias into _ROUTE_ALIASES.
    _fhir_reference_data._ROUTE_ALIASES["INTRAVENOUS"] = "IV"
    try:
        resource = _build_medication_admin(
            {
                "drug_name": "Norepinephrine",
                "dose": "0.1 mcg/kg/min CONTINUOUS",
                "route": "INTRAVENOUS",  # alias form, not the canonical "IV"
                "status": "given",
            },
            patient_id="POP-000001",
            index=1,
            country="JP",
            encounter_id="ENC-POP-000001-000000000001",
        )
        # `device` MUST still be present — the gate resolved the alias.
        assert "device" in resource, (
            "adding an alias for IV dropped device[]; the _is_infusion gate is comparing "
            "raw route text instead of the canonical form (canonicalize_route)"
        )
    finally:
        del _fhir_reference_data._ROUTE_ALIASES["INTRAVENOUS"]
