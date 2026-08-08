# AD-30 Display-in-CIF Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove 3 display-text fields (`AllergyReaction.manifestation_display`, `Allergy.allergen_display`, `ImagingSeries.body_site_display`) from CIF dataclasses so CIF stores codes only (AD-30), fixing the one live consumer (`allergen_display` in narrative generation) that has no `code_lookup()` wiring, and adding import-time SNOMED validation as the safety net for unresolvable codes.

**Architecture:** Three field removals across `clinosim/types/`, their producer enrichers (`allergy/engine.py`, `imaging/engine.py`), and their consumers (2 FHIR builders + 1 narrative template method). Extends 2 already-existing `_validate_*` loader functions (rather than creating new ones) to cross-check SNOMED codes against `clinosim.codes`. Test fixtures across 6 files are updated to match the new field-free shape.

**Tech Stack:** Python 3.11+, `dataclasses`, `pytest`.

## Global Constraints

- No comments explaining WHAT code does; only WHY, and only when non-obvious (project CLAUDE.md convention).
- AD-30: CIF stores codes only, not display text — display resolved at output time via `clinosim.codes.lookup()`.
- `code_lookup(system, code, lang)` returns the code itself (never `None`/exception) when a code isn't found — this is why validators use direct-membership checks (`_code_in_data`), not `lookup()`'s return value, to detect missing codes.
- `_code_in_data` is NOT a shared helper in this codebase — it's independently duplicated per-module (`hai/engine.py`, `order/panel_grouping.py`). New copies for `allergy/engine.py`/`imaging/engine.py` follow this same local-duplication pattern (a promotion-to-shared-helper TODO already exists, tracked separately, not part of this chain).
- Run `pytest -x -q` (or at minimum `pytest -m "unit or integration" -q`) after every task before committing.
- Source of design decisions: `docs/superpowers/specs/2026-07-04-ad30-display-in-cif-removal-design.md`.

---

### Task 1: Remove `AllergyReaction.manifestation_display` (dead field, FHIR-fallback-only)

**Files:**
- Modify: `clinosim/types/allergy.py:14-19` (`AllergyReaction` dataclass)
- Modify: `clinosim/modules/allergy/engine.py:137-143` (`allergy_enricher`)
- Modify: `clinosim/modules/output/_fhir_allergy_intolerance.py:145-167` (`_build_allergy_intolerance`, reaction loop)
- Test: `tests/unit/test_types_allergy.py`
- Test: `tests/unit/output/test_fhir_allergy_intolerance.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `AllergyReaction` no longer has a `manifestation_display` field. Later tasks (2, 3) touch different classes/files and don't depend on this one.

- [ ] **Step 1: Remove the field from the dataclass**

In `clinosim/types/allergy.py`, find:
```python
@dataclass
class AllergyReaction:
    """Allergic reaction manifestation."""

    manifestation_snomed: str = ""    # SNOMED CT code
    manifestation_display: str = ""   # locale-resolved display
    severity: str = "mild"            # mild / moderate / severe
```
Replace with:
```python
@dataclass
class AllergyReaction:
    """Allergic reaction manifestation."""

    manifestation_snomed: str = ""    # SNOMED CT code
    severity: str = "mild"            # mild / moderate / severe
```

- [ ] **Step 2: Remove the assignment in the enricher**

In `clinosim/modules/allergy/engine.py`, find (inside `allergy_enricher`):
```python
                reactions=[
                    AllergyReaction(
                        manifestation_snomed=reaction_entry["manifestation_snomed"],
                        manifestation_display=reaction_entry["manifestation_display_en"],
                        severity=reaction_entry["severity"],
                    )
                ],
```
Replace with:
```python
                reactions=[
                    AllergyReaction(
                        manifestation_snomed=reaction_entry["manifestation_snomed"],
                        severity=reaction_entry["severity"],
                    )
                ],
```

- [ ] **Step 3: Remove the fallback in the FHIR builder**

In `clinosim/modules/output/_fhir_allergy_intolerance.py`, find (inside `_build_allergy_intolerance`, the reaction loop):
```python
    for rxn in reactions_raw:
        manifestation_snomed = _o(rxn, "manifestation_snomed", "") or ""
        manifestation_display = _o(rxn, "manifestation_display", "") or ""
        severity = _o(rxn, "severity", "mild") or "mild"

        # Resolve manifestation display via code_lookup (locale-aware).
        if manifestation_snomed:
            _rm = code_lookup("snomed-ct", manifestation_snomed, lang)
            resolved_manifestation = _rm if _rm != manifestation_snomed else (manifestation_display or manifestation_snomed)
        else:
            resolved_manifestation = manifestation_display
```
Replace with:
```python
    for rxn in reactions_raw:
        manifestation_snomed = _o(rxn, "manifestation_snomed", "") or ""
        severity = _o(rxn, "severity", "mild") or "mild"

        # Resolve manifestation display via code_lookup (locale-aware, AD-30 —
        # CIF stores the code only; import-time validation guarantees every
        # manifestation_snomed in allergens.yaml resolves).
        resolved_manifestation = code_lookup("snomed-ct", manifestation_snomed, lang) if manifestation_snomed else ""
```

- [ ] **Step 4: Update `tests/unit/test_types_allergy.py`**

Find:
```python
def test_allergy_full_payload():
    reaction = AllergyReaction(
        manifestation_snomed="247472004",
        manifestation_display="Rash",
        severity="moderate",
    )
    a = Allergy(
        allergy_id="al-pt1-1",
        allergen_code="387207008",
        allergen_display="Penicillin",
        category="medication",
        criticality="high",
        verification_status="confirmed",
        onset_date=date(2020, 6, 15),
        reactions=[reaction],
    )
    assert a.allergen_display == "Penicillin"
    assert a.reactions[0].severity == "moderate"
```
Replace with (the `allergen_display` kwarg/assert removal is covered here too, since this test touches both fields — Task 3 will not need to revisit this test):
```python
def test_allergy_full_payload():
    reaction = AllergyReaction(
        manifestation_snomed="247472004",
        severity="moderate",
    )
    a = Allergy(
        allergy_id="al-pt1-1",
        allergen_code="387207008",
        category="medication",
        criticality="high",
        verification_status="confirmed",
        onset_date=date(2020, 6, 15),
        reactions=[reaction],
    )
    assert a.allergen_code == "387207008"
    assert a.reactions[0].severity == "moderate"
```

- [ ] **Step 5: Update `tests/unit/output/test_fhir_allergy_intolerance.py`**

Find `_sample_allergy_dataclass()`:
```python
def _sample_allergy_dataclass() -> Allergy:
    return Allergy(
        allergy_id="a01",
        allergen_code="372687004",
        allergen_display="Amoxicillin",
        category="medication",
        criticality="high",
        verification_status="confirmed",
        onset_date=date(2020, 3, 15),
        reactions=[
            AllergyReaction(
                manifestation_snomed="271807003",
                manifestation_display="Rash",
                severity="mild",
            ),
        ],
    )
```
Replace with (this removes `allergen_display` too, covering Task 3's part of this file — Task 3 does not need to revisit this helper):
```python
def _sample_allergy_dataclass() -> Allergy:
    return Allergy(
        allergy_id="a01",
        allergen_code="372687004",
        category="medication",
        criticality="high",
        verification_status="confirmed",
        onset_date=date(2020, 3, 15),
        reactions=[
            AllergyReaction(
                manifestation_snomed="271807003",
                severity="mild",
            ),
        ],
    )
```

Find `_sample_allergy_dict()`:
```python
def _sample_allergy_dict() -> dict:
    return {
        "allergy_id": "a01",
        "allergen_code": "372687004",
        "allergen_display": "Amoxicillin",
        "category": "medication",
        "criticality": "high",
        "verification_status": "confirmed",
        "onset_date": date(2020, 3, 15),
        "reactions": [
            {
                "manifestation_snomed": "271807003",
                "manifestation_display": "Rash",
                "severity": "mild",
            }
        ],
    }
```
Replace with:
```python
def _sample_allergy_dict() -> dict:
    return {
        "allergy_id": "a01",
        "allergen_code": "372687004",
        "category": "medication",
        "criticality": "high",
        "verification_status": "confirmed",
        "onset_date": date(2020, 3, 15),
        "reactions": [
            {
                "manifestation_snomed": "271807003",
                "severity": "mild",
            }
        ],
    }
```

Find `test_code_snomed_allergen` (this test's docstring/comment references `allergen_display`, update the comment to match reality post-removal):
```python
def test_code_snomed_allergen():
    # allergen_code "372687004" = Aspirin in SNOMED. code_lookup resolves to "Aspirin"
    # (locale-aware, overrides the fixture's allergen_display "Amoxicillin").
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    coding = r["code"]["coding"][0]
    assert coding["code"] == "372687004"
    assert "snomed" in coding["system"].lower() or "snomed.info" in coding["system"]
    assert r["code"]["text"] == "Aspirin"
```
Replace with:
```python
def test_code_snomed_allergen():
    # allergen_code "372687004" = Aspirin in SNOMED. code_lookup resolves to "Aspirin".
    ctx = _make_ctx([_sample_allergy_dataclass()])
    r = _bb_allergy_intolerances(ctx)[0]
    coding = r["code"]["coding"][0]
    assert coding["code"] == "372687004"
    assert "snomed" in coding["system"].lower() or "snomed.info" in coding["system"]
    assert r["code"]["text"] == "Aspirin"
```

Find `test_jp_locale_resolves_snomed_display_to_ja`:
```python
def test_jp_locale_resolves_snomed_display_to_ja():
    """JP cohort: allergen_code 387207008 (Penicillin) resolved to ペニシリン via code_lookup."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "387207008"
    a.allergen_display = "Penicillin"
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["code"]["coding"][0]["display"] == "ペニシリン"
    assert r["code"]["text"] == "ペニシリン"
```
Replace with:
```python
def test_jp_locale_resolves_snomed_display_to_ja():
    """JP cohort: allergen_code 387207008 (Penicillin) resolved to ペニシリン via code_lookup."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "387207008"
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    assert r["code"]["coding"][0]["display"] == "ペニシリン"
    assert r["code"]["text"] == "ペニシリン"
```

Find `test_jp_locale_resolves_reaction_manifestation_to_ja`:
```python
def test_jp_locale_resolves_reaction_manifestation_to_ja():
    """JP cohort: manifestation_snomed 247472004 (Rash) resolved to 発疹 via code_lookup."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "387207008"
    a.allergen_display = "Penicillin"
    a.reactions = [
        AllergyReaction(
            manifestation_snomed="247472004",
            manifestation_display="Rash",
            severity="moderate",
        )
    ]
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    rxn = r["reaction"][0]
    manifestation = rxn["manifestation"][0]
    assert manifestation["coding"][0]["display"] == "発疹"
    assert manifestation["text"] == "発疹"
```
Replace with:
```python
def test_jp_locale_resolves_reaction_manifestation_to_ja():
    """JP cohort: manifestation_snomed 247472004 (Rash) resolved to 発疹 via code_lookup."""
    a = _sample_allergy_dataclass()
    a.allergen_code = "387207008"
    a.reactions = [
        AllergyReaction(
            manifestation_snomed="247472004",
            severity="moderate",
        )
    ]
    ctx = _make_ctx([a], country="JP")
    r = _bb_allergy_intolerances(ctx)[0]
    rxn = r["reaction"][0]
    manifestation = rxn["manifestation"][0]
    assert manifestation["coding"][0]["display"] == "発疹"
    assert manifestation["text"] == "発疹"
```

Find `test_multiple_allergies_all_emitted`:
```python
def test_multiple_allergies_all_emitted():
    a1 = _sample_allergy_dataclass()
    a2 = _sample_allergy_dataclass()
    a2.allergy_id = "a02"
    a2.allergen_code = "70618"
    a2.allergen_display = "Penicillin"
    ctx = _make_ctx([a1, a2])
```
Replace with:
```python
def test_multiple_allergies_all_emitted():
    a1 = _sample_allergy_dataclass()
    a2 = _sample_allergy_dataclass()
    a2.allergy_id = "a02"
    a2.allergen_code = "387207008"
    ctx = _make_ctx([a1, a2])
```
(`allergen_code` changed from the non-SNOMED value `"70618"` to a real registered SNOMED code `387207008` (Penicillin) — with the display fallback gone, an unregistered code would still resolve via `code_lookup` to the bare code string, which is harmless for this test's assertions, but using a real code keeps the fixture consistent with the rest of the file's registered-code convention.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_types_allergy.py tests/unit/output/test_fhir_allergy_intolerance.py -v`
Expected: all tests PASS.

- [ ] **Step 7: Run the full unit + integration suite**

Run: `pytest -m "unit or integration" -q`
Expected: all pass except any tests covered in Tasks 2/3 that haven't been fixed yet (if running standalone before those tasks land, `clinosim/modules/patient/test_patient.py`, `tests/unit/test_narrative_context_wiring.py`, and `tests/unit/modules/document/narrative/test_template_generator.py` will still fail — this is expected until Task 3 lands; note it in your report but don't attempt to fix files outside this task's scope).

- [ ] **Step 8: Commit**

```bash
git add clinosim/types/allergy.py clinosim/modules/allergy/engine.py clinosim/modules/output/_fhir_allergy_intolerance.py tests/unit/test_types_allergy.py tests/unit/output/test_fhir_allergy_intolerance.py
git commit -m "fix(ad30): remove dead AllergyReaction.manifestation_display CIF field"
```

---

### Task 2: Remove `ImagingSeries.body_site_display` (dead field, FHIR-fallback-only)

**Files:**
- Modify: `clinosim/types/imaging.py:23-29` (`ImagingSeries` dataclass)
- Modify: `clinosim/modules/imaging/engine.py:286-293,305-312` (`_expand_views_to_series`)
- Modify: `clinosim/modules/output/_fhir_imaging_study.py:113-140` (`_build_series`)
- Modify: `clinosim/modules/imaging/audit.py:87-96` (synthetic proof data)
- Test: `tests/unit/test_types_imaging.py`
- Test: `tests/unit/output/test_fhir_imaging_study.py`

**Interfaces:**
- Consumes: nothing from other tasks (independent of Task 1/3 — different file, different class).
- Produces: `ImagingSeries` no longer has a `body_site_display` field.

- [ ] **Step 1: Remove the field from the dataclass**

In `clinosim/types/imaging.py`, find:
```python
    body_site_snomed: str = ""
    body_site_display: str = ""         # locale 解決前(en/ja 共通 key)
    description: str = ""
```
Replace with:
```python
    body_site_snomed: str = ""
    description: str = ""
```

- [ ] **Step 2: Remove both assignments in the enricher**

In `clinosim/modules/imaging/engine.py`, find (inside `_expand_views_to_series`, first branch):
```python
            series_list.append(ImagingSeries(
                series_number=i,
                modality_code=order_modality,
                body_site_snomed=body_site_snomed,
                body_site_display=body_site_display,
                description=f"{view} view",
                instance_count=instance_count,
            ))
```
Replace with:
```python
            series_list.append(ImagingSeries(
                series_number=i,
                modality_code=order_modality,
                body_site_snomed=body_site_snomed,
                description=f"{view} view",
                instance_count=instance_count,
            ))
```

Find (second branch, same function):
```python
            series_list.append(ImagingSeries(
                series_number=i,
                modality_code=order_modality,
                body_site_snomed=body_site_snomed,
                body_site_display=body_site_display,
                description=f"{view} acquisition",
                instance_count=instance_count,
            ))
```
Replace with:
```python
            series_list.append(ImagingSeries(
                series_number=i,
                modality_code=order_modality,
                body_site_snomed=body_site_snomed,
                description=f"{view} acquisition",
                instance_count=instance_count,
            ))
```

Also remove the now-unused local variable a few lines above both call sites. Find:
```python
    mod_def = modalities[order_modality]
    body_site_snomed = body_sites[body_site_key]["snomed"]
    body_site_display = body_sites[body_site_key]["display_en"]
```
Replace with:
```python
    mod_def = modalities[order_modality]
    body_site_snomed = body_sites[body_site_key]["snomed"]
```

- [ ] **Step 3: Remove the fallback in the FHIR builder**

In `clinosim/modules/output/_fhir_imaging_study.py`, find (inside `_build_series`):
```python
def _build_series(series: Any, lang: str) -> dict[str, Any]:
    """Build one FHIR R4 ImagingStudy.series element from an ImagingSeries."""
    snomed_system = get_system_uri("snomed-ct")
    body_site_snomed = _o(series, "body_site_snomed", "")
    # Resolve body site display via code registry; fall back to CIF display field.
    body_site_display = code_lookup("snomed-ct", body_site_snomed, lang) or _o(
        series, "body_site_display", "",
    )
```
Replace with:
```python
def _build_series(series: Any, lang: str) -> dict[str, Any]:
    """Build one FHIR R4 ImagingStudy.series element from an ImagingSeries."""
    snomed_system = get_system_uri("snomed-ct")
    body_site_snomed = _o(series, "body_site_snomed", "")
    # Resolve body site display via code registry (AD-30 — CIF stores the code
    # only; import-time validation guarantees every body_sites.yaml SNOMED
    # code resolves).
    body_site_display = code_lookup("snomed-ct", body_site_snomed, lang)
```

- [ ] **Step 4: Clean up the synthetic proof data in `imaging/audit.py`**

Find (inside the function building the synthetic `ImagingStudyRecord`):
```python
            ImagingSeries(
                series_uid="1.2.3.4.series-proof-1",
                series_number=1,
                modality_code="CR",
                body_site_snomed="51185008",
                body_site_display="Chest",
                description="PA view",
                instance_count=1,
            )
```
Replace with:
```python
            ImagingSeries(
                series_uid="1.2.3.4.series-proof-1",
                series_number=1,
                modality_code="CR",
                body_site_snomed="51185008",
                description="PA view",
                instance_count=1,
            )
```

- [ ] **Step 5: Update `tests/unit/test_types_imaging.py`**

Find:
```python
def test_imaging_series_defaults_are_no_op():
    s = ImagingSeries()
    assert s.series_uid == ""
    assert s.series_number == 1
    assert s.modality_code == ""
    assert s.body_site_snomed == ""
    assert s.body_site_display == ""
    assert s.description == ""
    assert s.instance_count == 0
```
Replace with:
```python
def test_imaging_series_defaults_are_no_op():
    s = ImagingSeries()
    assert s.series_uid == ""
    assert s.series_number == 1
    assert s.modality_code == ""
    assert s.body_site_snomed == ""
    assert s.description == ""
    assert s.instance_count == 0
```

- [ ] **Step 6: Update `tests/unit/output/test_fhir_imaging_study.py`**

Find `_sample_study()`:
```python
        series=[
            ImagingSeries(series_uid="2.25.43", series_number=1, modality_code="CR",
                          body_site_snomed="51185008", body_site_display="Thoracic structure",
                          description="PA view", instance_count=1),
            ImagingSeries(series_uid="2.25.44", series_number=2, modality_code="CR",
                          body_site_snomed="51185008", body_site_display="Thoracic structure",
                          description="Lateral view", instance_count=1),
        ],
```
Replace with:
```python
        series=[
            ImagingSeries(series_uid="2.25.43", series_number=1, modality_code="CR",
                          body_site_snomed="51185008",
                          description="PA view", instance_count=1),
            ImagingSeries(series_uid="2.25.44", series_number=2, modality_code="CR",
                          body_site_snomed="51185008",
                          description="Lateral view", instance_count=1),
        ],
```

Find `test_emits_imaging_study_from_dict_path`'s `study_dict`:
```python
        "series": [{
            "series_uid": "2.25.43", "series_number": 1,
            "modality_code": "CR", "body_site_snomed": "51185008",
            "body_site_display": "Thoracic structure",
            "description": "PA view", "instance_count": 1,
        }],
```
Replace with:
```python
        "series": [{
            "series_uid": "2.25.43", "series_number": 1,
            "modality_code": "CR", "body_site_snomed": "51185008",
            "description": "PA view", "instance_count": 1,
        }],
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/unit/test_types_imaging.py tests/unit/output/test_fhir_imaging_study.py -v`
Expected: all tests PASS (including `test_jp_locale_resolves_modality_and_body_site_ja`, which already asserts `code_lookup`-resolved display and needs no change).

- [ ] **Step 8: Run the full unit + integration suite**

Run: `pytest -m "unit or integration" -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add clinosim/types/imaging.py clinosim/modules/imaging/engine.py clinosim/modules/output/_fhir_imaging_study.py clinosim/modules/imaging/audit.py tests/unit/test_types_imaging.py tests/unit/output/test_fhir_imaging_study.py
git commit -m "fix(ad30): remove dead ImagingSeries.body_site_display CIF field"
```

---

### Task 3: Remove `Allergy.allergen_display` + fix its live narrative consumer

**Files:**
- Modify: `clinosim/types/allergy.py:22-33` (`Allergy` dataclass)
- Modify: `clinosim/modules/allergy/engine.py:128-134` (`allergy_enricher`)
- Modify: `clinosim/modules/output/_fhir_allergy_intolerance.py:80-104` (`_build_allergy_intolerance`)
- Modify: `clinosim/modules/document/narrative/template_generator.py:748-769` (`_build_allergies`)
- Modify: `clinosim/modules/document/audit.py:809-824` (synthetic proof data)
- Modify: `clinosim/modules/patient/test_patient.py:54-68`
- Test: `tests/unit/test_narrative_context_wiring.py`
- Test: `tests/unit/modules/document/narrative/test_template_generator.py`

**Interfaces:**
- Consumes: nothing from Task 1/2 (different field on `Allergy`, not `AllergyReaction`; independent).
- Produces: `Allergy` no longer has an `allergen_display` field. `_build_allergies()` in `template_generator.py` now resolves display via `code_lookup("snomed-ct", allergen_code, ctx.target_lang)`, following the exact same pattern already used by `_build_discharge_diagnoses()` in the same file (lines 929-976).

- [ ] **Step 1: Remove the field from the dataclass**

In `clinosim/types/allergy.py`, find:
```python
@dataclass
class Allergy:
    """Patient allergy/intolerance(AD-30 code-only CIF)."""

    allergy_id: str = ""              # patient-internal id
    allergen_code: str = ""           # SNOMED for allergen substance
    allergen_display: str = ""        # locale-resolved display
    category: str = ""                # "medication" / "food" / "environment"
```
Replace with:
```python
@dataclass
class Allergy:
    """Patient allergy/intolerance(AD-30 code-only CIF)."""

    allergy_id: str = ""              # patient-internal id
    allergen_code: str = ""           # SNOMED for allergen substance
    category: str = ""                # "medication" / "food" / "environment"
```

- [ ] **Step 2: Remove the assignment in the enricher**

In `clinosim/modules/allergy/engine.py`, find (inside `allergy_enricher`):
```python
        patient.allergies = [
            Allergy(
                allergy_id="1",  # FHIR builder owns the canonical "allergy-{patient_id}-{idx}" format (I-4 fix)
                allergen_code=entry["allergen_code"],
                allergen_display=entry["allergen_display_en"],
                category=category,
```
Replace with:
```python
        patient.allergies = [
            Allergy(
                allergy_id="1",  # FHIR builder owns the canonical "allergy-{patient_id}-{idx}" format (I-4 fix)
                allergen_code=entry["allergen_code"],
                category=category,
```

- [ ] **Step 3: Remove the fallback in the FHIR builder**

In `clinosim/modules/output/_fhir_allergy_intolerance.py`, find (inside `_build_allergy_intolerance`):
```python
def _build_allergy_intolerance(allergy: Any, patient_id: str, lang: str = "en") -> dict[str, Any] | None:
    """Build one FHIR R4 AllergyIntolerance from an Allergy (dataclass or dict)."""
    allergen_code = _o(allergy, "allergen_code", "") or ""
    allergen_display = _o(allergy, "allergen_display", "") or ""
    if not allergen_code and not allergen_display:
        return None

    allergy_id = _o(allergy, "allergy_id", "") or ""
    category_raw = (_o(allergy, "category", "") or "").lower()
    category = category_raw if category_raw in _VALID_CATEGORIES else "medication"
    criticality = _o(allergy, "criticality", "low") or "low"
    verification_status = _o(allergy, "verification_status", "confirmed") or "confirmed"
    onset_date = _o(allergy, "onset_date", None)

    snomed_system = get_system_uri("snomed-ct")

    # Resolve allergen display via code_lookup (locale-aware).
    # code_lookup returns the code itself when not found, so compare against
    # allergen_code to detect "not found" and fall through to allergen_display.
    if allergen_code:
        _r = code_lookup("snomed-ct", allergen_code, lang)
        resolved_display = _r if _r != allergen_code else (allergen_display or allergen_code)
    else:
        resolved_display = allergen_display or allergen_code
```
Replace with:
```python
def _build_allergy_intolerance(allergy: Any, patient_id: str, lang: str = "en") -> dict[str, Any] | None:
    """Build one FHIR R4 AllergyIntolerance from an Allergy (dataclass or dict)."""
    allergen_code = _o(allergy, "allergen_code", "") or ""
    if not allergen_code:
        return None

    allergy_id = _o(allergy, "allergy_id", "") or ""
    category_raw = (_o(allergy, "category", "") or "").lower()
    category = category_raw if category_raw in _VALID_CATEGORIES else "medication"
    criticality = _o(allergy, "criticality", "low") or "low"
    verification_status = _o(allergy, "verification_status", "confirmed") or "confirmed"
    onset_date = _o(allergy, "onset_date", None)

    snomed_system = get_system_uri("snomed-ct")

    # Resolve allergen display via code_lookup (locale-aware, AD-30 — CIF
    # stores the code only; import-time validation guarantees every
    # allergen_code in allergens.yaml resolves).
    resolved_display = code_lookup("snomed-ct", allergen_code, lang)
```

Also update the docstring's no-drop invariant comment near the top of the file. Find:
```python
  allergen_code        -> AllergyIntolerance.code.coding[SNOMED]
  allergen_display     -> AllergyIntolerance.code.text (locale-resolved)
```
Replace with:
```python
  allergen_code        -> AllergyIntolerance.code.coding[SNOMED] + .code.text (via code_lookup)
```

And:
```python
    manifestation_snomed -> reaction.manifestation[*].coding[SNOMED]
    manifestation_display -> reaction.manifestation[*].text
```
Replace with:
```python
    manifestation_snomed -> reaction.manifestation[*].coding[SNOMED] + .text (via code_lookup)
```

- [ ] **Step 4: Fix the narrative pipeline — `_build_allergies()` in `template_generator.py`**

In `clinosim/modules/document/narrative/template_generator.py`, find:
```python
    def _build_allergies(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build allergies section from ctx.allergies."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        allergies = ctx.allergies or []
        if not allergies:
            return _NKDA_JA if is_ja else _NKDA_EN, facts

        facts.append("ctx.allergies")
        parts = []
        for allergy in allergies:
            display = _o(allergy, "allergen_display", "") or ""
            criticality = _o(allergy, "criticality", "") or ""
            if display:
                if criticality:
                    crit_str = f"（{criticality}）" if is_ja else f" ({criticality})"
                    parts.append(f"{display}{crit_str}")
                else:
                    parts.append(display)
        return "; ".join(parts) if parts else (_NKDA_JA if is_ja else _NKDA_EN), facts
```
Replace with:
```python
    def _build_allergies(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build allergies section from ctx.allergies.

        Resolves display via code_lookup (AD-30 — CIF stores allergen_code
        only, not display text; this mirrors _build_discharge_diagnoses'
        code_lookup pattern in this same file).
        """
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        allergies = ctx.allergies or []
        if not allergies:
            return _NKDA_JA if is_ja else _NKDA_EN, facts

        facts.append("ctx.allergies")
        parts = []
        for allergy in allergies:
            allergen_code = _o(allergy, "allergen_code", "") or ""
            display = code_lookup("snomed-ct", allergen_code, lang) if allergen_code else ""
            criticality = _o(allergy, "criticality", "") or ""
            if display:
                if criticality:
                    crit_str = f"（{criticality}）" if is_ja else f" ({criticality})"
                    parts.append(f"{display}{crit_str}")
                else:
                    parts.append(display)
        return "; ".join(parts) if parts else (_NKDA_JA if is_ja else _NKDA_EN), facts
```

- [ ] **Step 5: Update `clinosim/modules/document/audit.py` synthetic proof data**

Find:
```python
    # Synthetic Allergy (Penicillin SNOMED 372687004, in clinosim/codes/data/snomed-ct.yaml).
    allergy_data = {
        "allergy_id": "a001",
        "allergen_code": "372687004",
        "allergen_display": "Penicillin",
        "category": "medication",
        "criticality": "high",
        "verification_status": "confirmed",
        "onset_date": None,
        "reactions": [
            {
                "manifestation_snomed": "",
                "manifestation_display": "Rash",
                "severity": "mild",
            }
        ],
    }
```
Replace with:
```python
    # Synthetic Allergy (Penicillin SNOMED 372687004, in clinosim/codes/data/snomed-ct.yaml).
    allergy_data = {
        "allergy_id": "a001",
        "allergen_code": "372687004",
        "category": "medication",
        "criticality": "high",
        "verification_status": "confirmed",
        "onset_date": None,
        "reactions": [
            {
                "manifestation_snomed": "",
                "severity": "mild",
            }
        ],
    }
```

- [ ] **Step 6: Update `clinosim/modules/patient/test_patient.py`**

Find:
```python
        allergies=[
            Allergy(
                allergy_id="al-P-ALPHA-001-1",
                allergen_code="303408005",
                allergen_display="Sulfonamide",
                category="medication",
                criticality="low",
                verification_status="confirmed",
                reactions=[AllergyReaction(
                    manifestation_snomed="247472004",
                    manifestation_display="Rash",
                    severity="mild",
                )],
            ),
        ],
```
Replace with:
```python
        allergies=[
            Allergy(
                allergy_id="al-P-ALPHA-001-1",
                allergen_code="303408005",
                category="medication",
                criticality="low",
                verification_status="confirmed",
                reactions=[AllergyReaction(
                    manifestation_snomed="247472004",
                    severity="mild",
                )],
            ),
        ],
```

- [ ] **Step 7: Update `tests/unit/test_narrative_context_wiring.py`**

Find (the fixture dict):
```python
            "allergies": [
                {"allergen_display": "Penicillin", "criticality": "high"},
            ],
```
Replace with:
```python
            "allergies": [
                {"allergen_code": "387207008", "criticality": "high"},
            ],
```

Find:
```python
def test_allergies_read_from_patient_allergies():
    ctx = _build_ctx(_patient_dict())
    assert len(ctx.allergies) == 1
    assert ctx.allergies[0]["allergen_display"] == "Penicillin"
```
Replace with:
```python
def test_allergies_read_from_patient_allergies():
    """Context building passes allergies through unresolved — display
    resolution happens later, in TemplateNarrativeGenerator._build_allergies
    via code_lookup (AD-30)."""
    ctx = _build_ctx(_patient_dict())
    assert len(ctx.allergies) == 1
    assert ctx.allergies[0]["allergen_code"] == "387207008"
```

- [ ] **Step 8: Update `tests/unit/modules/document/narrative/test_template_generator.py`**

Find:
```python
def test_allergies_listed_in_admission_hp() -> None:
    """Allergies in ctx must appear in allergies section of ADMISSION_HP."""
    from clinosim.types.allergy import Allergy
    allergy = Allergy(allergen_display="ペニシリン", criticality="high", category="medication")
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(
        document_type=DocumentType.ADMISSION_HP,
        disease_protocol=protocol,
        allergies=[allergy],
        target_lang="ja",
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    allergy_text = out.sections.get("allergies", "")
    assert "ペニシリン" in allergy_text, (
        f"Allergy 'ペニシリン' not found in: {allergy_text!r}"
    )
```
Replace with:
```python
def test_allergies_listed_in_admission_hp() -> None:
    """Allergies in ctx must appear in allergies section of ADMISSION_HP,
    resolved via code_lookup (AD-30 — allergen_code 387207008 = Penicillin,
    ja display ペニシリン, per clinosim/codes/data/snomed-ct.yaml)."""
    from clinosim.types.allergy import Allergy
    allergy = Allergy(allergen_code="387207008", criticality="high", category="medication")
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(
        document_type=DocumentType.ADMISSION_HP,
        disease_protocol=protocol,
        allergies=[allergy],
        target_lang="ja",
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    allergy_text = out.sections.get("allergies", "")
    assert "ペニシリン" in allergy_text, (
        f"Allergy 'ペニシリン' not found in: {allergy_text!r}"
    )
```

- [ ] **Step 9: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_narrative_context_wiring.py tests/unit/modules/document/narrative/test_template_generator.py -v -k "allerg"
pytest tests/unit/test_types_allergy.py tests/unit/output/test_fhir_allergy_intolerance.py -v
```
Expected: all PASS. (`test_types_allergy.py`/`test_fhir_allergy_intolerance.py` were already fixed in Task 1 — re-running here confirms Task 3's additional edits to the same files, per Step 1/Step 5 of Task 1's plan, didn't regress.)

- [ ] **Step 10: Run the full unit + integration suite**

Run: `pytest -m "unit or integration" -q`
Expected: all pass — this is the task that closes out every remaining reference to `allergen_display`, so this should be fully green now (assuming Tasks 1 and 2 already landed).

- [ ] **Step 11: Commit**

```bash
git add clinosim/types/allergy.py clinosim/modules/allergy/engine.py clinosim/modules/output/_fhir_allergy_intolerance.py clinosim/modules/document/narrative/template_generator.py clinosim/modules/document/audit.py clinosim/modules/patient/test_patient.py tests/unit/test_narrative_context_wiring.py tests/unit/modules/document/narrative/test_template_generator.py
git commit -m "fix(ad30): remove Allergy.allergen_display, fix narrative pipeline to use code_lookup"
```

---

### Task 4: Import-time SNOMED validation for allergy + imaging YAML loaders

**Files:**
- Modify: `clinosim/modules/allergy/engine.py:30-89` (`_validate_allergens`, `load_allergens`)
- Modify: `clinosim/modules/imaging/engine.py:89-183` (`_validate_body_sites`, `load_body_sites`)
- Test: `tests/unit/modules/allergy/test_engine.py` (or create if it doesn't already cover validators — check first)
- Test: `tests/unit/modules/imaging/test_engine.py` (same check)

**Interfaces:**
- Consumes: nothing from Tasks 1-3 (these are the loader/validator functions, independent of the dataclass field removals — they validate the YAML source data, not CIF output).
- Produces: `_validate_allergens()` now raises `ValueError` if any `allergen_code` or `common_reactions[].manifestation_snomed` isn't a registered SNOMED code. `_validate_body_sites()` now raises `ValueError` if any body site's `snomed` isn't registered. Both add a local `_code_in_data(system, code) -> bool` helper (following the existing pattern in `clinosim/modules/hai/engine.py:174-196`).

- [ ] **Step 1: Check for existing validator test coverage**

Run: `grep -rn "_validate_allergens\|_validate_body_sites" tests/`

If tests already exist for these functions, add new test cases to those files. If none exist, create `tests/unit/modules/allergy/test_validate_allergens.py` and `tests/unit/modules/imaging/test_validate_body_sites.py` (check whether `tests/unit/modules/allergy/` and `tests/unit/modules/imaging/` directories already exist first — use whichever convention this codebase already follows for per-module test directories, matching the existing `tests/unit/modules/allergy/test_allergens_yaml.py` file's location if that's where allergy YAML validation tests already live).

- [ ] **Step 2: Write the failing tests**

Add these test functions (adjust the target file per Step 1's finding):

```python
import pytest


def test_validate_allergens_raises_on_unregistered_allergen_code():
    from clinosim.modules.allergy.engine import _validate_allergens
    data = {
        "allergens": {
            "medication": [{
                "allergen_code": "99999999999",  # not in snomed-ct.yaml
                "allergen_display_en": "Fake Drug",
                "allergen_display_ja": "偽薬",
                "prevalence": {"adult": 0.1},
                "criticality": "low",
                "common_reactions": [{
                    "manifestation_snomed": "247472004",
                    "manifestation_display_en": "Rash",
                    "manifestation_display_ja": "発疹",
                    "severity": "mild",
                }],
            }],
            "food": [],
            "environment": [],
        }
    }
    with pytest.raises(ValueError, match="99999999999"):
        _validate_allergens(data)


def test_validate_allergens_raises_on_unregistered_manifestation_snomed():
    from clinosim.modules.allergy.engine import _validate_allergens
    data = {
        "allergens": {
            "medication": [{
                "allergen_code": "387207008",  # Penicillin, registered
                "allergen_display_en": "Penicillin",
                "allergen_display_ja": "ペニシリン",
                "prevalence": {"adult": 0.1},
                "criticality": "low",
                "common_reactions": [{
                    "manifestation_snomed": "99999999999",  # not registered
                    "manifestation_display_en": "Fake",
                    "manifestation_display_ja": "偽",
                    "severity": "mild",
                }],
            }],
            "food": [],
            "environment": [],
        }
    }
    with pytest.raises(ValueError, match="99999999999"):
        _validate_allergens(data)


def test_validate_body_sites_raises_on_unregistered_snomed():
    from clinosim.modules.imaging.engine import _validate_body_sites
    data = {
        "body_sites": {
            "chest": {
                "snomed": "99999999999",  # not registered
                "display_en": "Chest",
                "display_ja": "胸部",
                "procedure_codes": {
                    "cr": {
                        "loinc": "36554-4", "cpt": "71046",
                        "jp_k_code": "K001", "display_en": "X-ray",
                        "display_ja": "X線",
                    },
                },
            },
            "head": {
                "snomed": "69536005",
                "display_en": "Head",
                "display_ja": "頭部",
                "procedure_codes": {
                    "ct": {
                        "loinc": "24725-4", "cpt": "70450",
                        "jp_k_code": "K002", "display_en": "CT",
                        "display_ja": "CT",
                    },
                },
            },
        }
    }
    with pytest.raises(ValueError, match="99999999999"):
        _validate_body_sites(data)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest -k "test_validate_allergens_raises_on_unregistered or test_validate_body_sites_raises_on_unregistered" -v`
Expected: all 3 FAIL (validators don't yet check SNOMED registration — either they pass without raising, or `_validate_allergens`/`_validate_body_sites` don't exist yet under that exact test path; either way, the tests must fail before the fix).

- [ ] **Step 4: Add `_code_in_data` + extend `_validate_allergens` in `clinosim/modules/allergy/engine.py`**

Find:
```python
def _validate_allergens(data: dict[str, Any]) -> None:
    """Fail-loud validation of allergens.yaml (silent-no-op defense Layer 3-6).

    Layer 3: empty top + per-bucket guards
    Layer 4: forward + reverse coverage vs SUPPORTED_ALLERGEN_CATEGORIES
    Layer 5: validator runs BEFORE data is returned (pre-register ordering)
    Layer 6: required-field check per entry + prevalence range 0..1
    """
```
Replace with:
```python
def _code_in_data(system: str, code: str) -> bool:
    """Direct membership check in codes/data/<system>.yaml.

    `lookup()` returns the code itself as fallback for unknown entries (not
    None), so it can't distinguish "code exists" from "code absent". Direct
    `cs.codes` membership IS the authoritative check (same pattern as
    `hai/engine.py:_code_in_data`).
    """
    from clinosim.codes.loader import _load_system

    cs = _load_system(system)
    if cs is None:
        raise ValueError(
            f"_code_in_data: code system {system!r} not registered in "
            f"clinosim/codes/data/ — system itself is missing, not the code"
        )
    return code in cs.codes


def _validate_allergens(data: dict[str, Any]) -> None:
    """Fail-loud validation of allergens.yaml (silent-no-op defense Layer 3-6).

    Layer 3: empty top + per-bucket guards
    Layer 4: forward + reverse coverage vs SUPPORTED_ALLERGEN_CATEGORIES
    Layer 5: validator runs BEFORE data is returned (pre-register ordering)
    Layer 6: required-field check per entry + prevalence range 0..1
    Layer 6b (AD-30 chain): allergen_code + every common_reactions[].manifestation_snomed
      must resolve in codes/data/snomed-ct.yaml (safety net now that the CIF
      no longer carries a fallback display string for unresolvable codes).
    """
```

Find (end of the per-entry validation loop, right after the `common_reactions` non-empty check):
```python
            reactions = e.get("common_reactions", [])
            if not reactions or not isinstance(reactions, list):
                raise ValueError(
                    f"allergens.yaml[{cat}][{i}].common_reactions: must be non-empty list"
                )
```
Replace with:
```python
            reactions = e.get("common_reactions", [])
            if not reactions or not isinstance(reactions, list):
                raise ValueError(
                    f"allergens.yaml[{cat}][{i}].common_reactions: must be non-empty list"
                )
            allergen_code = e["allergen_code"]
            if not _code_in_data("snomed-ct", allergen_code):
                raise ValueError(
                    f"allergens.yaml[{cat}][{i}].allergen_code {allergen_code!r} "
                    f"not in codes/data/snomed-ct.yaml"
                )
            for j, rxn in enumerate(reactions):
                manifestation_snomed = rxn.get("manifestation_snomed", "")
                if not manifestation_snomed:
                    raise ValueError(
                        f"allergens.yaml[{cat}][{i}].common_reactions[{j}]: missing manifestation_snomed"
                    )
                if not _code_in_data("snomed-ct", manifestation_snomed):
                    raise ValueError(
                        f"allergens.yaml[{cat}][{i}].common_reactions[{j}].manifestation_snomed "
                        f"{manifestation_snomed!r} not in codes/data/snomed-ct.yaml"
                    )
```

- [ ] **Step 5: Add `_code_in_data` + extend `_validate_body_sites` in `clinosim/modules/imaging/engine.py`**

Find:
```python
def _validate_body_sites(data: dict[str, Any]) -> None:
    """Fail-loud validation of body_sites.yaml (forward + reverse coverage)."""
```
Replace with:
```python
def _code_in_data(system: str, code: str) -> bool:
    """Direct membership check in codes/data/<system>.yaml.

    `lookup()` returns the code itself as fallback for unknown entries (not
    None), so it can't distinguish "code exists" from "code absent". Direct
    `cs.codes` membership IS the authoritative check (same pattern as
    `hai/engine.py:_code_in_data`).
    """
    from clinosim.codes.loader import _load_system

    cs = _load_system(system)
    if cs is None:
        raise ValueError(
            f"_code_in_data: code system {system!r} not registered in "
            f"clinosim/codes/data/ — system itself is missing, not the code"
        )
    return code in cs.codes


def _validate_body_sites(data: dict[str, Any]) -> None:
    """Fail-loud validation of body_sites.yaml (forward + reverse coverage).

    AD-30 chain addition: every body site's `snomed` must resolve in
    codes/data/snomed-ct.yaml — safety net now that the CIF no longer carries
    a fallback display string for unresolvable codes.
    """
```

Find:
```python
    for bs_key, bs in body_sites.items():
        if not bs.get("snomed"):
            raise ValueError(f"body_sites.yaml[{bs_key}]: missing snomed")
```
Replace with:
```python
    for bs_key, bs in body_sites.items():
        if not bs.get("snomed"):
            raise ValueError(f"body_sites.yaml[{bs_key}]: missing snomed")
        if not _code_in_data("snomed-ct", bs["snomed"]):
            raise ValueError(
                f"body_sites.yaml[{bs_key}].snomed {bs['snomed']!r} "
                f"not in codes/data/snomed-ct.yaml"
            )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest -k "test_validate_allergens_raises_on_unregistered or test_validate_body_sites_raises_on_unregistered" -v`
Expected: all 3 PASS.

- [ ] **Step 7: Run the full unit + integration suite**

Run: `pytest -m "unit or integration" -q`
Expected: all pass — this confirms the REAL `allergens.yaml`/`body_sites.yaml` (loaded at import time by every test that touches these modules) contain only registered SNOMED codes; if this fails, the real YAML has a data-quality bug this validator correctly caught (fix the YAML, don't weaken the validator).

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/allergy/engine.py clinosim/modules/imaging/engine.py
git add <the test file(s) from Step 1/2>
git commit -m "feat(ad30): validate allergen/body-site SNOMED codes against codes registry at import time"
```

---

### Task 5: TODO.md — record the locale-freeze bug as a separate deferred item

**Files:**
- Modify: `TODO.md`

**Interfaces:** none (docs-only).

- [ ] **Step 1: Add the deferred entry**

Find the `### Single items (ride along with related chains)` section in `TODO.md` (same section used by prior chains for small standalone follow-ups) and add one entry, matching the existing bullet style in that section:

```markdown
- Allergy/imaging display locale-freeze — `clinosim/modules/allergy/reference_data/allergens.yaml`
  and `clinosim/modules/imaging/reference_data/body_sites.yaml` carry both `display_en` and
  `display_ja` per entry, but `allergy/engine.py`'s `allergy_enricher()` and
  `imaging/engine.py`'s `_expand_views_to_series()` only ever read the `_en` variant when
  populating YAML-sourced fields consumed elsewhere (unrelated to the AD-30 chain's CIF
  fields, which are code-only after that chain — this is about the YAML data's own
  locale handling for any future en/ja-sensitive consumer of these loaders). Not a CIF
  violation; a distinct localization gap. Fixing requires threading `lang`/`country`
  into the relevant loader call sites and selecting `display_en`/`display_ja` accordingly.
```

- [ ] **Step 2: Commit**

```bash
git add TODO.md
git commit -m "docs: track allergy/imaging locale-freeze as separate deferred item"
```

---

### Task 6: Final verification sweep

**Files:** none modified (verification only, unless the grep in Step 1 finds an unexpected gap)

- [ ] **Step 1: Grep for any remaining reference to the removed fields**

Run:
```bash
grep -rn "manifestation_display\|allergen_display\|body_site_display" clinosim/ tests/ --include="*.py"
```
Expected: zero hits. If any remain, they are either a missed call site (fix it) or a stale comment (update the comment — comments referencing removed fields are misleading and must be updated, not left).

- [ ] **Step 2: Run the full test suite**

Run: `pytest -x -q`
Expected: all unit + integration + e2e tests pass.

- [ ] **Step 3: Golden regeneration check**

Run:
```bash
clinosim regenerate-goldens --all
git status --short tests/fixtures/patient_profiles/
```
Three allergen codes have a CIF-stored display that diverges from `code_lookup()`'s canonical text (per the design spec §5): `303408005` "Sulfa drugs"→"Sulfonamide", `227037002` "Eggs"→"Egg", `256262001` "Pollen"→"Tree pollen". If regeneration changes any `.golden.json` file's narrative text, inspect the diff: confirm it comes from an allergy-bearing patient whose enricher-sampled allergen happens to be one of these three codes (i.e., the new text reflects the correct `code_lookup()` value), and confirm — per AD-66 Rule 2 — that no *other* profile's golden changed unexpectedly. Commit the regenerated goldens together with an explanatory note in the commit message if any changed.

- [ ] **Step 4: `clinosim audit run` on a small US + JP cohort**

Run:
```bash
python -m clinosim.simulator.cli generate --population 50 --country US --seed 42 --format cif -o /tmp/ad30_audit_us
python -m clinosim.simulator.cli audit run -d /tmp/ad30_audit_us
python -m clinosim.simulator.cli generate --population 50 --country JP --seed 42 --format cif -o /tmp/ad30_audit_jp
python -m clinosim.simulator.cli audit run -d /tmp/ad30_audit_jp
```
Expected: `Overall: PASS` for both cohorts (adjust `-d` to `<output_dir>/cif` if `audit run` reports it can't find the cohort at the top-level path — check with `python -m clinosim.simulator.cli audit run --help` if the exact path shape is unclear).

- [ ] **Step 5: Manual FHIR export spot-check**

Run:
```bash
python -m clinosim.simulator.cli export-fhir --cif-dir /tmp/ad30_audit_us/cif -o /tmp/ad30_audit_us/fhir
grep -l "AllergyIntolerance" /tmp/ad30_audit_us/fhir/*.ndjson
```
Open one `AllergyIntolerance` resource from the NDJSON (if any US patient in this 50-population cohort has an allergy — with `OVERALL_ALLERGY_PREVALENCE = 0.15`, a 50-patient cohort should have several) and confirm `code.text` and `reaction[].manifestation[].text` are populated with real English display strings (not empty, not a bare SNOMED code number — a bare code number would indicate `code_lookup()` failed to resolve, which Task 4's validation should have already prevented at generation time). Repeat for the JP cohort's `ImagingStudy` resources if any imaging-eligible disease (`bacterial_pneumonia`, `aspiration_pneumonia`, `hemorrhagic_stroke`) occurs, confirming `series[].bodySite.display` is in Japanese.

- [ ] **Step 6: Commit (only if Step 3 produced golden changes not already committed in Step 3)**

If Step 3's golden regeneration wasn't already committed there, commit now:
```bash
git add tests/fixtures/patient_profiles/*.golden.json
git commit -m "chore(ad30): regenerate narrative goldens after allergen display resolution fix"
```

## Post-plan note for the executing agent

After Task 6, hand off to `superpowers:finishing-a-development-branch` to decide on PR vs direct merge, following this repo's established pattern for chains of this size (5 files touched across 3 modules + 2 FHIR builders + 1 narrative generator + ~6 test files).
