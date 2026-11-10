# FHIR Data Generation — Logic Design Guide

**Status:** Active (2026-06-29, established with PR1 ServiceRequest).
**Audience:** any new developer adding or extending a clinosim FHIR
resource builder. Canonical layout: builders live under
`clinosim/modules/output/fhir_r4/` (per-domain sub-packages —
`conditions/`, `labs/`, `procedures/`, `documents/`, …); the
`_BUNDLE_BUILDERS` registry + `register_bundle_builder()` are defined in
`clinosim/modules/output/fhir_r4/builder.py` and re-exported from
`clinosim/modules/output/fhir_r4/__init__.py`.
**Scope:** Layer 4 = FHIR R4 resource builders only. CIF generation
(Layers 1-3) has a separate guide — see
[`docs/CONTRIBUTING-modules.md`](../CONTRIBUTING-modules.md).
**Binding spec:** code mapping, display resolution and localization
are governed by
[`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md);
where this guide and that spec disagree, the spec wins.

clinosim FHIR generation is a **thin conversion layer that takes CIF
as input and emits FHIR R4 resource dicts**. Its central concerns
are FHIR-spec / US-Core / JP-Core compliance, multilingual display
resolution, and identifier conventions.

The design rules on the CIF side (Layers 1-3 = reference YAML,
loader, CIF generation modules) are already detailed in
[`docs/CONTRIBUTING-modules.md`](../CONTRIBUTING-modules.md)
(canonical path constants / `@lru_cache` rules / the 6-layer +
7-layer system defense / sub-seed / panel-aware grouping / etc.).
Do not duplicate them — this guide covers **only the FHIR builder
layer's responsibilities**.

First-pass reading order = A → B → C → D. E is anti-patterns, F is
reference material.

---

## A. FHIR builder layer's place and responsibility

```
            ┌──────────────────────────────────────────┐
  CIF →     │ Layer 4: FHIR builders (fhir_r4/<domain>/*.py)      │  → FHIR R4 NDJSON
            │  - read CIF (record / record.extensions) │     (Bulk Data Export)
            │  - read clinosim.codes (display lookup)  │
            │  - read clinosim.locale (locale display) │
            │  - import canonical loaders from CIF     │
            │    side (panel definitions, HAI types …) │
            │  - emit FHIR R4 resource dicts           │
            │  - registered via _BUNDLE_BUILDERS or    │
            │    register_bundle_builder (AD-56)       │
            └──────────────────────────────────────────┘
```

**FHIR builder responsibilities / non-responsibilities**:

| Layer 4 does | Layer 4 does not |
|---|---|
| Read CIF (record / extensions / orders / lab_results / …) | Mutate CIF |
| Resolve display via `display(...) or <fallback>` and build coded concepts with `dual_slot_concept()` | Hard-code display strings |
| Resolve system URI via `get_system_uri()` | Hard-code system URIs |
| **Import** canonical constants (`SR_ID_PREFIX`, etc.) **from the owner module** | Re-define constants inside the builder |
| Import Layer 2 loaders (`load_panel_definitions`, etc.) | Open raw YAML inside the builder |
| Convention `urn:clinosim:...` for `identifier.system` | Ad-hoc private namespaces |
| Emit resources shaped by FHIR R4 / US Core / JP Core specs | Add fields outside the spec ad-hoc |

---

## B. How to add a new FHIR resource (How to)

### B.1 Overall flow (7 steps)

| Step | Content | See |
|---|---|---|
| 1 | Prepare the required field / extensions on the CIF side (assumed complete) | CIF guide = `docs/CONTRIBUTING-modules.md` |
| 2 | Create a new builder file `clinosim/modules/output/fhir_r4/<domain>/<topic>.py` | Section B.2 |
| 3 | Define canonical constants (ID prefix, identifier system) inside the builder | Section B.3 |
| 4 | Implement resource-skeleton functions (via `dual_slot_concept` / `display` / `get_system_uri`) | Section B.4 |
| 5 | Implement the builder entry point `_bb_<topic>(ctx: BundleContext) -> list[dict]` | Section B.5 |
| 6 | Register in `clinosim/modules/output/fhir_r4/builder.py:_BUNDLE_BUILDERS` OR add via `register_bundle_builder()` | Section B.6 |
| 7 | Add unit + integration tests + audit `lift_firing_proof`, and verify the output change by byte-diff | Section C |

### B.2 File template

```python
# clinosim/modules/output/fhir_r4/<domain>/<topic>.py
"""<Topic> FHIR R4 builder.

Reads CIF (record.extensions["<topic>"] or record.<field>), emits FHIR R4
<ResourceType> resources. Complies with US Core / JP Core <topic> profile.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import display, get_system_uri
from clinosim.countries import lang_for
from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

# Canonical constants — single definition site, consumers import (Section B.3)
TOPIC_ID_PREFIX = "tp-"
TOPIC_IDENTIFIER_SYSTEM = "urn:clinosim:identifier:<topic>-id"


def _bb_<topic>(ctx: BundleContext) -> list[dict]:
    """Builder entry point — emit <ResourceType> resources from CIF.

    Returns an empty list when no relevant CIF data exists (clean no-op for
    cohorts that don't carry this topic). Audit framework verifies non-empty
    emission for cohorts that DO carry it.
    """
    items = ctx.record.get("extensions", {}).get("<topic>") or []
    if not items:
        return []
    return [_build_resource(item, ctx) for item in items]


def _build_resource(item, ctx: BundleContext) -> dict:
    lang = lang_for(ctx.country)   # canonical idiom — no inline branching (E.10)
    res = {
        "resourceType": "<ResourceType>",
        "id": f"{TOPIC_ID_PREFIX}{item.id_field}",
        "identifier": [{
            "system": TOPIC_IDENTIFIER_SYSTEM,
            "value": item.id_field,
        }],
        "subject": {"reference": f"Patient/{ctx.patient_id}"},
        # Coded concept: English-only systems (LOINC, SNOMED CT) keep the English
        # coding.display and carry the JP label in .text (code-mapping spec §5.3).
        "code": dual_slot_concept("loinc", item.loinc_code, lang),
        # ... display(...) or <explicit fallback> for any other display,
        # get_system_uri() for any system
    }
    # Encounter ref, requester, dates, code, category, etc. per the FHIR profile.
    return res
```

### B.3 Canonical constants — single-definition site

Place canonical constants (ID prefix, identifier system, category
constants, etc.) inside the builder:

```python
# clinosim/modules/output/fhir_r4/<domain>/<topic>.py (writer = canonical owner)
TOPIC_ID_PREFIX = "tp-"                                       # FHIR Resource.id prefix
TOPIC_IDENTIFIER_SYSTEM = "urn:clinosim:identifier:topic-id"  # identifier.system URI
TOPIC_CATEGORY_SNOMED = "..."                                 # category SNOMED code
```

Import them from **audit modules / consumer modules / reader tests**:

```python
# clinosim/modules/<owner>/audit.py (reader)
from clinosim.modules.output.fhir_r4.<domain>.<topic> import (
    TOPIC_ID_PREFIX, TOPIC_IDENTIFIER_SYSTEM,
)
```

**When a third consumer appears, import it as well** — do not
re-define.

### B.4 Display resolution — `dual_slot_concept` and `display`

A coded `CodeableConcept` is built at the emit site with
`dual_slot_concept` (`clinosim/modules/output/fhir_r4/lib/common.py`);
a `Coding`-typed element with no `text` slot (`Encounter.class`) uses
`system_coding`. Both apply the dual-slot rule of code-mapping spec
§5.3: for an English-only system (`is_english_only_system` — LOINC,
SNOMED CT, HL7 terminology, DICOM, UCUM) `coding.display` stays the
English canonical display in every locale, and the JP label goes in
`CodeableConcept.text`. Other systems (JP Core, JP-CLINS, MEDIS, YJ,
clinosim-owned) keep the display in the output language.

```python
lang = lang_for(ctx.country)
code = dual_slot_concept("loinc", panel_loinc_code, lang, fallback_display=fallback_text)
# JP: {"coding": [{"system": "http://loinc.org", "code": ..., "display": <English>}],
#      "text": <Japanese label>}
```

When only the display string is needed, call `display(...)` from
`clinosim.codes` with an explicit fallback (code-mapping spec §4.1,
§9 — `lookup(...)` is not used in new code):

```python
icd_display = display("icd-10-cm", icd_code, lang) or ""
```

- 1st argument = the code-system key (`"loinc"` / `"icd-10-cm"` /
  `"snomed-ct"` / `"rxnorm"` / `"jlac10"` / `"k-codes"` / `"cpt"` /
  etc.).
- 3rd argument = the output language, always derived via
  `lang_for(ctx.country)` (`clinosim/countries/__init__.py`); inline branching
  is forbidden (E.10).
- Return value = display string; `None` when absent (fall back with
  `or`).
- Using the code itself as display is AD-30 violation + multilingual
  breakage = NG.

**When the code system itself changes by country** (lab =
JLAC10 / LOINC, diagnosis = ICD-10 / ICD-10-CM, drug = YJ / RxNorm,
procedure = K-codes / CPT), pick the key with
`clinosim.codes.system_key_for(kind, country)` (shared-logic
unification 2026-07-02, single source of truth; unknown `kind`
raises `KeyError` fail-loud):

```python
from clinosim.codes import system_key_for

system_key = system_key_for("lab", ctx.country)      # JP → "jlac10", else → "loinc"
concept = dual_slot_concept(system_key, code, lang_for(ctx.country))
```

System URI:

```python
sr["code"]["coding"][0]["system"] = get_system_uri("loinc")
```

- `get_system_uri("loinc")` → `"http://loinc.org"`
- `get_system_uri("snomed-ct")` → `"http://snomed.info/sct"`
- `get_system_uri("icd-10-cm")` → `"http://hl7.org/fhir/sid/icd-10-cm"`

Do not hard-code the string. Register a new system key's canonical
HL7 URI in `codes/loader.py:_BUILTIN_URIS` before using it (recent
additions 2026-07-02: `hl7-endpoint-connection-type` /
`hl7-endpoint-payload-type` / `hl7-subscriber-relationship`).

### B.5 Builder entry point + BundleContext interface

```python
def _bb_<topic>(ctx: BundleContext) -> list[dict]:
```

`BundleContext` (existing, `clinosim/modules/output/fhir_r4/lib/context.py`)
is the uniform input to a builder:

| Field | Purpose |
|---|---|
| `ctx.record` | CIF patient record (dict-like: `record.orders` / `record.lab_results` / `record.extensions[X]`, etc.) |
| `ctx.country` | `"US"` / `"JP"` — passed to `lang_for` for the output language and to `is_jp` / `is_us` for country rules |
| `ctx.patient_id` | For resolving `Patient/<id>` references |
| `ctx.primary_enc_id` | Primary encounter id |
| `ctx.roster_map` | Staff roster lookup |
| `ctx.hospital_config` | Hospital config (department, ward, etc.) |
| `ctx.is_readmission`, `ctx.prior_encounter_id` | Readmission context |
| `ctx.primary_dx_code`, `ctx.admit_dx_code` | Encounter dx codes |

A builder touches only fields on `ctx` (no global state — preserves
AD-16).

### B.6 Registering the builder (AD-56)

**Built-in resource (near-essential / always-on)** = append to the
`_BUNDLE_BUILDERS` list directly:

```python
# clinosim/modules/output/fhir_r4/builder.py
from clinosim.modules.output.fhir_r4.<domain>.<topic> import _bb_<topic>

_BUNDLE_BUILDERS: list[Callable[[BundleContext], list[dict]]] = [
    _bb_patient,
    # ... existing
    _bb_<topic>,   # ← insert in the right emission-order position
]
```

Emission-order guideline: order by **reference resolution direction**.
Patient → Encounter → Observation → ServiceRequest (which
Observation's `basedOn` refers to) → DiagnosticReport (which
references Observations). Placing ServiceRequest before Observation
keeps the intra-NDJSON references strictly forward-resolvable.

**Opt-in module (AD-55 Module)** = call `register_bundle_builder()`
at import time:

```python
# clinosim/modules/<topic>/__init__.py or a startup hook
from clinosim.modules.output.fhir_r4 import register_bundle_builder
from clinosim.modules.output.fhir_r4.<domain>.<topic> import _bb_<topic>
register_bundle_builder(_bb_<topic>)
```

`register_bundle_builder` deduplicates (double registration of the
same-named builder is ignored).

---

## C. Tests & verification

### C.1 Unit test (`pytest -m unit`)

Call the builder function directly. Construct a minimal
`BundleContext` fixture:

```python
# tests/unit/output/test_fhir_<topic>.py
from datetime import datetime
from clinosim.codes import display
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.<domain>.<topic> import _bb_<topic>

def _make_ctx(extensions_topic_data, country="us"):
    return BundleContext(
        record={"extensions": {"<topic>": extensions_topic_data}},
        country=country,
        roster_map={}, hospital_config={}, patient_data={},
        patient_id="pt1", is_readmission=False, prior_encounter_id=None,
        primary_dx_code="", admit_dx_code="",
    )

def test_emits_resource_when_extension_present():
    items = [build_test_item()]
    resources = _bb_<topic>(_make_ctx(items))
    assert len(resources) == 1
    assert resources[0]["resourceType"] == "<ResourceType>"

def test_empty_extension_emits_zero_resources():
    assert _bb_<topic>(_make_ctx([])) == []

def test_identifier_carries_canonical_system():
    resources = _bb_<topic>(_make_ctx([build_test_item()]))
    assert resources[0]["identifier"][0]["system"] == TOPIC_IDENTIFIER_SYSTEM

def test_jp_locale_keeps_english_coding_display_and_ja_text():
    item = build_test_item()
    resources = _bb_<topic>(_make_ctx([item], country="jp"))
    concept = resources[0]["code"]
    # LOINC is English-only: coding.display stays English, the JP label is in .text
    assert concept["coding"][0]["display"] == display("loinc", item.loinc_code, "en")
    assert concept["text"] == display("loinc", item.loinc_code, "ja")
```

### C.2 Integration test (`pytest -m integration`)

Generate a small cohort via `run_beta` and verify NDJSON:

```python
import json, subprocess, tempfile
from pathlib import Path

@pytest.mark.integration
def test_<topic>_ndjson_emitted_with_proper_references():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        subprocess.run(["clinosim", "run-beta", "--country", "us",
                        "--population", "100", "--seed", "42", "--output", str(out)],
                       check=True)
        with (out / "<ResourceType>.ndjson").open() as f:
            resources = [json.loads(l) for l in f if l.strip()]
        assert len(resources) > 0
        # reference integrity:
        patient_ids = ...  # load Patient.ndjson, build set
        for r in resources:
            assert r["subject"]["reference"].removeprefix("Patient/") in patient_ids
```

Always run an integrity check on cross-resource references such as
`basedOn`.

### C.3 Determinism test (AD-16)

```python
@pytest.mark.integration
def test_<topic>_ndjson_byte_identical_across_runs():
    hashes = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            subprocess.run(["clinosim", "run-beta", "--country", "us",
                            "--population", "50", "--seed", "42", "--output", str(out)],
                           check=True, capture_output=True)
            hashes.append(hashlib.sha256((out / "<ResourceType>.ndjson").read_bytes()).hexdigest())
    assert hashes[0] == hashes[1]
```

### C.4 Audit module (★ silent-no-op gate, AD-60)

Add a **`lift_firing_proof`** to `clinosim/modules/<owner>/audit.py`
(5+ equality_checks):

```python
from clinosim.modules.output.fhir_r4.<domain>.<topic> import (
    TOPIC_ID_PREFIX, TOPIC_IDENTIFIER_SYSTEM,
)

register_audit_module(ModuleAuditSpec(
    name="<topic>_fhir",
    structural_checks=[
        "every <ResourceType>.identifier[0].system == TOPIC_IDENTIFIER_SYSTEM",
        "every <ResourceType>.id starts with TOPIC_ID_PREFIX",
        "every subject reference resolves in Patient.ndjson",
    ],
    clinical_acceptance={"emission_rate": "...(n<30 → WARN)"},
    jp_language_checks=[
        "code.text in Japanese for JP locale; code.coding[].display English for English-only systems",
    ],
    lift_firing_proof={
        "equality_checks": [
            f"TOPIC_IDENTIFIER_SYSTEM == '{TOPIC_IDENTIFIER_SYSTEM}'",
            "ResourceCount > 0 when extensions['<topic>'] non-empty",
            "ref integrity holds in NDJSON",
            # ... 5+ canonical-constant + emission proofs
        ],
    },
))
```

Detail: see `docs/CONTRIBUTING-modules.md` § "3-axis DQR
procedure" (the AD-60 `clinosim audit run` gate).

### C.5 Goldens and byte-diff

There is no golden FHIR NDJSON in the repository. A new resource
changes the exported NDJSON, and that change is verified by
byte-diffing the same seed's export before and after the PR (the
difference must be exactly the intended one). The goldens that do
exist are:

- `tests/e2e/test_alpha_golden.py` — structural counts of one forced
  seed-42 patient, held inline in the test; update them only when
  the simulator's behaviour changes intentionally.
- `tests/fixtures/patient_profiles/*.golden.json` (and
  `*.llm-mock.golden.json`) — the narrative goldens of the canonical
  patient profiles (AD-66, `pytest -m regression`), regenerated with
  `clinosim regenerate-goldens`.

Detail: `docs/CONTRIBUTING-modules.md` § "PR verification guide:
byte-diff vs 3-axis DQR".

---

## D. Conventions (FHIR-specific)

### D.1 `Resource.id` naming convention

| Resource | Shape | Example |
|---|---|---|
| ServiceRequest (panel) | `sr-{encounter_id}-{panel_key}-{N}` | `sr-enc-pt001-001-CBC-1` |
| ServiceRequest (stand-alone) | `sr-{order_id}` | `sr-ORD-pt001-ADM-L05` |
| Observation (lab) | `lab-{encounter_id}-{seq}` | `lab-enc-pt001-001-0001` |
| Observation (vital sign) | `vs-{encounter_id}-{seq}` | `vs-enc-pt001-001-0001` |
| Observation (microorganism) | `mb-org-{...}` (MB_ORG_ID_PREFIX) | — |
| HAIEvent identifier | `hai-{enc}-{type}-{n}` | `hai-enc1-cauti-1` |

Prefixes live at the writer as **canonical constants**; readers
import them.

### D.2 `identifier.system` URI convention

```
urn:clinosim:identifier:<concept>      # generic internal identifier
urn:clinosim:placer-order-number       # ServiceRequest placerOrderNumber (PR1)
urn:clinosim:identifier:hai-event-id   # HAI culture cross-ref (PR3b-5)
urn:clinosim:staff                     # staff / practitioner internal id
```

New = add under the same namespace as a constant
(`<TOPIC>_IDENTIFIER_SYSTEM` or `<TOPIC>_ID_SYSTEM`).

### D.3 Multilingual coding (AD-46)

Condition / Procedure / ServiceRequest etc. use **dual coding — the
country's local code system + an interop code system**:

```python
"code": {
    "coding": [
        # Primary: country's local code system (US = ICD-10-CM, JP = ICD-10 WHO + JP-K)
        system_coding(local_key, local_code, lang),
        # Interop: SNOMED CT is English-only, so its display stays English in every locale
        system_coding("snomed-ct", snomed_code, lang),
    ],
    "text": short_clinical_name,   # label in the output language; never == code; never raw enum
}
```

Each coding follows the dual-slot rule (code-mapping spec §5.3); the
output-language label lives in `text`.

### D.4 JP localization conventions

The output language comes from **`lang_for(ctx.country)`**;
**`is_jp(ctx.country)`** / **`is_us(ctx.country)`** are for country
rules only (reimbursement codes, profiles, JP-only sections), never
for picking a display (code-mapping spec §5.1, §9). All three live
in `clinosim/countries/__init__.py`. Do not write hand-rolled variants like
`ctx.country.lower() == "jp"` — E.10. For a JP cohort:

- `text` / `name` fields and the `coding.display` of non-English-only
  systems (JP Core, JP-CLINS, MEDIS, YJ, clinosim-owned) = Japanese,
  via `dual_slot_concept` / `system_coding` or
  `display(..., lang_for(ctx.country)) or <fallback>`.
- `coding.display` of English-only systems (LOINC, SNOMED CT, HL7
  terminology, DICOM, UCUM) = English; the Japanese label goes in
  `CodeableConcept.text` via `dual_slot_concept` (code-mapping spec
  §5.3). A Japanese display inside such a coding is a validation
  error.
- Country-dependent code-system selection (JLAC10 vs LOINC etc.) =
  `system_key_for(kind, ctx.country)` (E.11).
- Coded enum values (category / priority / interpretation etc.) = `dual_slot_concept()` over the code-keyed `codes/data/hl7-*.yaml` registry
  (existing helper, `clinosim/modules/output/fhir_r4/lib/common.py (localization helpers)`).
- Drug / procedure names = `display(...)` (or `drug_display` for a
  catalog drug) when a code or catalog id is held, otherwise the
  lang-aware free-text resolver `localize_drug_name(name, lang)` from
  `clinosim/locale/free_text.py` (re-exported by
  `output/fhir_r4/lib/localization.py`). The wrapper
  is a no-op for locales without a drug-name lookup table (today:
  any `lang != "ja"`), so callers stay single-code-path — no
  `if lang == "ja":` gate needed. Underlying `_localize_drug_name`
  (country-parameter form) remains for callers on the country
  seam; both are backed by the canonical cached loaders
  `clinosim/locale/loaders/narrative.py:load_narrative_display_dict()` /
  `clinosim/locale/loaders/medical_display.py:load_med_terms_ja()`
  (both still re-exported from `clinosim/locale/loader.py` as a
  compatibility façade post-B1/B2b split) — no raw-YAML reads
  inside the builder (E.3).
- Department display = `_dept_display()` (backed by
  `load_department_display()`).
- If no translation exists → EN fallback + audit warn list.

US cohort = 100 % English, zero Japanese characters.

### D.5 `referenceRange` + `interpretation` consistency (AD-47)

A numeric Observation **must** emit both `referenceRange` **and**
`interpretation`, and they must be consistent:

```python
obs["referenceRange"] = [{
    "low": {"value": low, "unit": unit},
    "high": {"value": high, "unit": unit},
}]
obs["interpretation"] = [{
    "coding": [{"system": "http://hl7.org/fhir/v3/ObservationInterpretation",
                "code": "H" if value > high else "L" if value < low else "N",
                "display": "High" if ... else "Low" if ... else "Normal"}],
}]
```

Lab interpretation is **recomputed** from value vs. `referenceRange`
at output time (do not blindly trust the CIF flag — verify
consistency at output).

### D.6 Reference integrity

Every `reference` field resolves inside the same NDJSON export:

```python
"subject": {"reference": f"Patient/{ctx.patient_id}"},
"encounter": {"reference": f"Encounter/{ctx.primary_enc_id}"},
"basedOn": [{"reference": f"ServiceRequest/{sr_id}"}],
```

A dangling reference = fail-loud in the audit's `clinical` axis.

---

## E. Anti-patterns (FHIR builder layer)

### E.1 ❌ Hard-coding display strings

```python
sr["code"]["coding"][0]["display"] = "Complete blood count (hemogram) panel..."  # NG
```

**Fix**: build the concept with `dual_slot_concept("loinc", code, lang)`
(or `display("loinc", code, lang) or <fallback>` when only the string
is needed).

### E.2 ❌ Hard-coding system URIs

```python
sr["code"]["coding"][0]["system"] = "http://loinc.org"  # NG
```

**Fix**: `get_system_uri("loinc")`.

### E.3 ❌ Opening raw YAML inside the builder

```python
def _bb_foo(ctx):
    panels = yaml.safe_load(open(SOME_PATH))  # NG — Layer 4 directly reads Layer 1
```

**Fix**: import the Layer-2 canonical loader
(`from clinosim.modules.order.panel_grouping import load_panel_definitions`).

**Precedent (shared-logic unification 2026-07-02)**:
`_fhir_localization.py` (now `fhir_r4/lib/localization.py`) used to load locale's shared YAML
(`med_terms_ja.yaml` / the retired `drug_names_ja.yaml` (deleted #1876; replaced by `load_narrative_display_dict` catalog UNION) /
`department_display.yaml`) with inline `yaml.safe_load` from inside
the builder — this has been moved to the canonical cached loaders in
`clinosim/locale/loaders/` (`medical_display.py:load_med_terms_ja()` /
`narrative.py:load_narrative_display_dict()` /
`medical_display.py:load_department_display()`), all re-exported
from `clinosim/locale/loader.py` for backward compatibility.
Builders that need locale data now import these — do not write
new inline YAML reads in a builder. Cached loader return values
are shared instances (mutation forbidden).

### E.4 ❌ Writing display strings into CIF (AD-30 violation)

An anti-pattern on the CIF-generation side, but the temptation to
mutate CIF from a FHIR builder is the same:

```python
def _build_resource(item, ctx):
    item.display_name_ja = display(..., "ja")   # NG — mutating CIF
```

**Fix**: treat CIF as read-only. Display resolution lives entirely
inside the returned builder-dict.

### E.5 ❌ Embedding the ID prefix as a string literal

```python
sr["id"] = f"sr-{order.order_id}"  # NG — "sr-" is a literal
```

**Fix**: import the `SR_ID_PREFIX = "sr-"` constant +
`f"{SR_ID_PREFIX}{order.order_id}"`.

### E.6 ❌ Two builders re-computing the same display

```python
# fhir_r4/labs/observations.py
display_a = display("loinc", "58410-2", "ja")
# fhir_r4/labs/diagnostic_report.py
display_b = display("loinc", "58410-2", "ja")
```

Technically fine, but if display post-processing (shortening,
formatting) is needed in both builders, factor it out into a shared
helper (e.g. in `fhir_r4/lib/common.py`).

### E.7 ❌ Ignoring Resource-id collisions

```python
sr["id"] = f"sr-{enc}-{panel}-1"   # multiple panels in the same encounter all pinned to 1 = collision
```

**Fix**: derive N deterministically via a per-encounter counter
(PR1 ServiceRequest `build_panel_counter` precedent).

### E.8 ❌ Japanese in an English-only coding, or no JP label in `text`

```python
sr["code"]["coding"][0]["display"] = display("loinc", code, "ja")  # NG — LOINC is English-only
sr["code"] = {"coding": [{"system": ..., "code": code,
                          "display": display("loinc", code, "en")}]}  # NG for JP — no .text label
```

**Fix**: `sr["code"] = dual_slot_concept("loinc", code, lang_for(ctx.country))`
— English `coding.display`, JP label in `text` (code-mapping spec
§5.3). For a non-English-only system, `dual_slot_concept` puts the
output-language display in the coding itself.

### E.9 ❌ Ad-hoc fields outside the FHIR R4 spec

```python
sr["my_custom_field"] = "..."   # NG — adding free fields on a Resource violates the spec
```

**Fix**: put spec-external data on the `extension[]` array (FHIR R4
`Extension` element) with a canonical URL.

### E.10 ❌ Hand-rolled country decision / language selection idioms

```python
if ctx.country == "JP": ...                              # NG
if ctx.country.lower() == "jp": ...                      # NG
lang = "ja" if str(ctx.country).upper() == "JP" else "en"  # NG
```

**Fix**: `from clinosim.countries import is_jp, lang_for`
— use only `lang_for(ctx.country)` for the output language and
`is_jp(ctx.country)` for country rules.
Before the shared-logic unification (2026-07-02), 5 divergent
idioms coexisted, and case-normalization differences could silently
disable JP gating (a PR-90-class risk). Both helpers are a single
normalization point (case-insensitive + strip).

### E.11 ❌ Inline country → code-system-key selection

```python
system_key = "jlac10" if ctx.country == "JP" else "loinc"   # NG — inline branching
```

**Fix**: `from clinosim.codes import system_key_for` —
`system_key_for("lab", ctx.country)`. Kinds = `"lab"` /
`"diagnosis"` / `"drug"` / `"procedure"` (jlac10 / loinc, icd-10 /
icd-10-cm, yj / rxnorm, k-codes / cpt). Unknown `kind` raises
`KeyError` fail-loud. The single source of truth for this selection
is the country profile's `code_systems` (`clinosim/locale/<cc>/country.yaml`).

---

## F. Principles (reference deep-dives)

### F.1 AD-30 — CIF is language-neutral

CIF holds codes only; display is resolved at output time (= Layer 4
builder) via `display()` / `dual_slot_concept()`. **Why**: adding a language or
changing a locale is entirely a matter of editing the `ja:` field
of `clinosim/codes/data/<system>.yaml` — zero ripple into the CIF
or generation modules.

### F.2 AD-31 — FHIR resource id globally unique within a type

No id collisions within a resource type. Canonical ID prefix (writer
↔ reader shared) + encounter-scoped counter → deterministic. **Why**:
any post-NDJSON consumer can resolve references.

### F.3 AD-46 — Multilingual coding

Dual coding on Condition / Procedure / ServiceRequest etc. (local
primary + interop secondary). **Why**: satisfy both a domestic EHR
and international interoperability.

### F.4 AD-47 — `referenceRange` + `interpretation` consistency

Both fields of a numeric Observation must be emitted; consistency
is verified at output time by recomputation. **Why**: blindly
trusting a CIF flag is a staleness risk; independent computation at
output time guarantees freshness.

### F.5 AD-56 — `register_bundle_builder`

Add a new resource type via the builder registry — do not edit
`_build_bundle()`. **Why**: a single extension point; a new-resource
PR does not touch the core simulator.

### F.6 AD-58 — `register_output_adapter`

Adding a new output format (non-FHIR = HL7 v2 / CSV / etc.) also
goes through a registry — do not edit the CLI `--format` dispatch.
**Why**: extension is possible along both the builder and adapter
dimensions.

### F.7 Reference-resolution invariant

Every `reference` field resolves inside the same NDJSON export —
dangling is not allowed. **Why**: dangling / empty `basedOn` is a
classic silent-no-op (PR-90 class): no audit gate → downstream NLP
/ EHR-migration tests break silently.

---

## Related

- [`docs/CONTRIBUTING-modules.md`](../CONTRIBUTING-modules.md) —
  full set of CIF-generation-side (Layers 1-3) design rules.
- `DESIGN.md` — ADRs AD-17 / AD-25 / AD-30 / AD-31 / AD-46 /
  AD-47 / AD-55 / AD-56 / AD-58 / AD-59 / AD-60 / AD-61.
- `AGENTS.md` — § "FHIR R4 output" / § "Common pitfalls".
  (`CLAUDE.md` remains
  as a thin pointer to `AGENTS.md` for older Claude Code sessions.)
- `.github/TEMPLATE_MODULE_README.md` — boilerplate for a new
  module README.

## Application precedents (FHIR builder layer)

Historical record: file names are as of each PR. The `_fhir_*.py`
modules have since moved to `clinosim/modules/output/fhir_r4/<domain>/`
(e.g. `_fhir_localization.py` → `fhir_r4/lib/localization.py`), and
the `Composition.author` TODO below has since been closed (it is now
emitted from `author_practitioner_id`).

| PR | Wins on the FHIR builder layer |
|---|---|
| FA-1 (PR #49–#59) | Split the monolithic FHIR adapter module into per-theme `_fhir_*` builders (3015 → 498 lines) |
| AD-46 (Multilingual coding) | Dual coding on Condition / Procedure |
| AD-47 (`refRange` + `interpretation`) | Observation consistency |
| PR-A 2026-06-26 | Applied the `_HERE / "reference_data"` canonical form on the builder side too |
| PR3b-5 (2026-06-29) | `HAI_EVENT_ID_SYSTEM` — cross-module canonical URI (writer = `_fhir_microbiology.py`, reader = `clinosim/audit/axes/clinical.py`) |
| **PR1 ServiceRequest (2026-06-29)** | **`_fhir_service_request.py` builder + `SR_ID_PREFIX` / `PLACER_ORDER_NUMBER_SYSTEM` / `LAB_CATEGORY_*` canonical constants + `_fhir_observations.basedOn` + `_fhir_diagnostic_report.basedOn` + AD-61 ADR** |
| **Tier 1 #3 DocumentReference (2026-07-01)** | **`_fhir_document_reference.py`**: `DOC_REFERENCE_ID_PREFIX = "doc-"`, reads `ClinicalDocument.text` (base64-encode inline), `ClinicalDocument.loinc_code` → `type.coding[0].code`, `ClinicalDocument.format_type == "free_text"` gate; `_o()` dual-access on the extensions dict; Patient + Encounter refs wired via `ctx.patient_id` / `ctx.primary_enc_id`. dict-path + dataclass-path tests required. |
| **Tier 1 #3 Composition (2026-07-01)** | **`_fhir_composition.py`**: `COMPOSITION_ID_PREFIX = "comp-"`, dispatched on `ClinicalDocument.format_type == "composition"`, reads the `ClinicalDocument.sections` dict (does NOT re-parse `raw_text` — the `ClinicalDocument.sections` field is authoritative per the AD-63 Task 8 fix), emits `section[]` with LOINC `title` + `text.div` per section key. `Composition.author = []` TODO pending practitioner-ref wiring (α-min-2). |
| **Tier 1 #3 ClinicalImpression (2026-07-01)** | **`_fhir_clinical_impression.py`**: `CLINICAL_IMPRESSION_ID_PREFIX = "ci-"`, reads `extensions["clinical_impressions"]` — a list of `ClinicalImpressionRecord` (dataclass); `_o()` dual-access for the dict path (production JSON-deserialized CIF), Patient + Encounter refs; `status = "completed"` for discharged encounters, `"in-progress"` for in-progress (AD-32 snapshot semantics). |
| **Tier 1 #3 AllergyIntolerance upgrade (2026-07-01)** | **`_fhir_allergy_intolerance.py`**: `ALLERGY_ID_PREFIX = "allergy-"`, reads `PersonRecord.allergies` (`list[Allergy]`). `code.coding[0]` = allergen SNOMED via `system_coding("snomed-ct", allergen_code, lang)` (English display in every locale; the JP label goes in `code.text`). `reaction[0].manifestation[0]` = reaction SNOMED. `criticality` / `category` / `clinicalStatus` / `verificationStatus` from `Allergy` dataclass fields. `_o()` dual-access for both the Allergy-dataclass (test fixture) and the dict (production) paths, per the CLAUDE.md rule. |
| **Tier 1 #3 `document_chain` audit (2026-07-01)** | **`clinosim/modules/document/audit.py`**: `ModuleAuditSpec` with `canonical_constants` (4 ID-prefix constants), `lift_firing_proof` callable (17 equality_checks), `clinical_acceptance` (a 5-key dict per spec §9.3). Follows `imaging/audit.py` precedent exactly. `discover()` auto-registers on import. |
| **Tier 1 #3 α-min-2 CareTeam (2026-07-01)** | **`_fhir_care_team.py`**: `CARE_TEAM_ID_PREFIX = "ct-"`, 1:1 with encounter invariant, reads `extensions["nursing_assignment"]` (NursingAssignmentRecord dataclass), emits an attending `participant[0]` (Practitioner ref via `ctx.primary_attending_id`) + a nurse `participant[1]` (Practitioner ref from `NursingAssignmentRecord.nurse_id`). `subject = Patient/X`, `encounter = Encounter/Y`. `category[0]` = SNOMED 305048009 (Inpatient care team). `status = "active"` for in-progress / `"inactive"` for discharged encounters. AD-32: in-progress encounters emit CareTeam (no discharge gating needed). |
| **Tier 1 #3 α-min-2 ADMISSION_NURSING_ASSESSMENT (2026-07-01)** | **LOINC 78390-2** (corrected from 47420-5 per a LOINC-DB query), DocumentReference (`doc-`) + Composition (`comp-`) format. Emitted by the `document` module enricher from the `document_type_specs.yaml` `encounter_types_supported: [inpatient, icu, rehabilitation]` allowlist gate. Sections: chief_complaint, vital_signs, pain_assessment, skin_assessment, fall_risk (Morse-scale score from the nursing flowsheet), functional_status, care_plan. |
| **Tier 1 #3 α-min-2 NURSING_SHIFT_NOTE (2026-07-01; α-min-3 3-shift cadence 2026-07-02)** | **LOINC 34746-8**, `generation_frequency: daily_3shift` = 3 notes per LOS day (night 00:00 / day 08:00 / evening 16:00, chronological; `engine.SHIFT_SCHEDULE` canonical constant). `format_type: free_text` → emitted as DocumentReference (`doc-`) only; `document_id` carries a shift-token suffix (`...-NN-night/day/evening`). Structural CIF stub stores the **neutral shift key** (`ClinicalDocument.shift`, AD-30 spirit); localized labels are resolved at Stage-2 render time (en: night / day / evening, ja: 深夜 / 日勤 / 準夜). Same skip rules as `daily`: LOS=1 same-day skip + AD-32 in-progress `los_days` proxy. `encounter_types_supported: [inpatient, icu, rehab_inpatient]`. |
| **Tier 1 #3 α-min-2 NURSING_DISCHARGE_SUMMARY (2026-07-01)** | **LOINC 34745-0**, emitted only for discharged encounters (AD-32 snapshot gate: skipped when `encounter.status == "in-progress"`). DocumentReference + Composition. Sections: discharge_condition, patient_education, home_care_instructions, follow_up_plan. `discharge_once = True` gate in the document enricher ensures exactly 1 per encounter. |
| **Tier 1 #3 α-min-2 OUTPATIENT_SOAP (2026-07-01)** | **LOINC 34131-3** (corrected from 11488-4 per a LOINC-DB query). `encounter_types_supported: [outpatient]`. Production wiring: `outpatient.py` calls `run_stage(POST_ENCOUNTER)` (α-min-2 Task 14 fix; verified 2026-07-02 — 1,841 Composition at US p=500 seed=42). |
| **Tier 1 #3 α-min-2 ED_NOTE + ED_TRIAGE_NOTE (2026-07-01)** | **ED_NOTE = LOINC 34878-9** (corrected from 51847-2), **ED_TRIAGE_NOTE = LOINC 54094-8** (checked and confirmed correct). `encounter_types_supported: [emergency]`. Production wiring: `emergency.py` calls `run_stage(POST_ENCOUNTER)` (α-min-2 Task 14 fix; verified 2026-07-02 — ED_NOTE 210 Composition + ED_TRIAGE_NOTE 210 DocumentReference at US p=500 seed=42). |
| **Tier 1 #2 Imaging (2026-06-30)** | **New `_fhir_imaging_study.py` + `_fhir_endpoint.py` + polymorphic `_fhir_service_request.py` imaging dispatch + radiology `_fhir_diagnostic_report.py` variant + canonical constants `IMAGING_CATEGORY_SNOMED` / `DICOM_UID_SYSTEM` / `ENDPOINT_ID_PREFIX` / `DICOM_WADO_RS_CONNECTION_TYPE` / `IMAGING_SR_ID_PREFIX` + CIF→FHIR no-drop invariant (1:1 ImagingStudyRecord → ImagingStudy + Endpoint + radiology DR + imaging SR) + AD-62 ADR + `encounter_id` invariant (all orders in `CIFPatientRecord.orders` must have non-empty `encounter_id` before FHIR export — inpatient.py unknown-condition fix 2026-06-30)** |
| **Common-logic unification (2026-07-02)** | **Established `is_jp` / `lang_for` (now in `clinosim/countries/__init__.py`) as the sole canonical idioms for JP country gating / output-language selection (replaced 5 divergent idioms — E.10) + `system_key_for(kind, country)` (`clinosim.codes`) = the single source of truth for country → code-system selection (E.11) + migrated `_fhir_localization.py`'s 3 inline YAML loaders to the canonical cached loaders in `clinosim/locale/loader.py` (`load_med_terms_ja` / `load_narrative_display_dict` / `load_department_display`; E.3 precedent) + added `hl7-endpoint-connection-type` / `hl7-endpoint-payload-type` / `hl7-subscriber-relationship` to `_BUILTIN_URIS` + moved aggregate loaders to their owner module (`load_all_disease_protocols` → `modules/disease/protocol.py`) + `@lru_cache`d the protocol / config loaders (shared instances = mutation forbidden)** |

Japanese counterpart: [`fhir-data-generation-logic.ja.md`](fhir-data-generation-logic.ja.md).
