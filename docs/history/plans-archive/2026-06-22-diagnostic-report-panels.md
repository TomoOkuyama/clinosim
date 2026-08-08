# DiagnosticReport panel grouping — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add post-hoc grouping of existing lab Observations into FHIR `DiagnosticReport` resources (CBC / BMP / LFT / Lipid / Coag / UA / ABG) at FHIR adapter emit time, leaving every non-DR NDJSON file byte-identical to master and preserving the existing microbiology DR emission unchanged.

**Architecture:** A new bundle builder (AD-56 `register_bundle_builder` pattern) walks each encounter's lab orders, groups by `(result_datetime[:16], lab_name → panel)` with a per-panel `min_components` threshold, emits one `DiagnosticReport` per group whose `result[]` references the already-emitted Observation ids. Microbiology DR emission stays in `_bb_microbiology`. Grouping is a pure function of `ctx.record["orders"]` (no RNG, no CIF schema read).

**Tech Stack:** Python 3.11+, ruff, mypy(strict), PyYAML for the new reference YAML, pytest. Determinism via AD-16 — no RNG draws.

## Global Constraints

- Code/comments/docstrings in English; line length 100; ruff formatter; mypy strict.
- **Byte-diff invariant gate** (US `p=2000 -s 42` and JP `p=2000 -s 42 --jp-insurance`): every NDJSON except `DiagnosticReport.ndjson` must be byte-identical to master; the existing microbiology DR records (`dr-mb-*`) must appear byte-identically in the new `DiagnosticReport.ndjson`; the file is allowed to grow with new `dr-{panel}-*` records appended after the microbiology section.
- Determinism (AD-16): no `random.random()`, no new RNG, no `numpy.random.Generator` usage.
- Authoritative LOINC panel codes (verified at <https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search>): CBC `58410-2`, BMP `51990-0`, LFT `24325-3`, Lipid `57698-3`, Coag `24373-3`, UA `24356-8`, ABG `24338-6`. **Never fabricate** — `# TODO: verify` allowed only when the lookup is pending.
- Each new LOINC code must be added to `clinosim/codes/data/loinc.yaml` with at least an `en` field per the project's code-coverage rule.
- AD-30 (CIF language-neutral): no CIF schema change. DR builder reads `ctx.record["orders"]` and constructs Observation references using the existing `lab-{enc_id}-{index:04d}` id format.
- AD-56 (extensibility): register the new builder via `register_bundle_builder()` (or by appending to `_BUNDLE_BUILDERS` at module load time). Do NOT edit the `_build_bundle()` function body.
- Branch hygiene: build on `feat/diagnostic-report-panels` (already created off master with `05f3c72a` committing the spec). Each task commit ends with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` and `Claude-Session: <session-url>`.

---

### Task 1: Add the 7 LOINC panel codes to `loinc.yaml`

**Files:**
- Modify: `clinosim/codes/data/loinc.yaml` (add 7 entries near the end of the file).

**Interfaces:**
- Consumes: nothing (data-only).
- Produces: `clinosim.codes.lookup("loinc", "58410-2", "en")` returns "Complete blood count (hemogram) panel - Blood by Automated count", and same for the other six panels. Other tasks rely on this lookup succeeding.

- [ ] **Step 1: Locate the end of `loinc.yaml`**

```bash
wc -l clinosim/codes/data/loinc.yaml
tail -5 clinosim/codes/data/loinc.yaml
```

Expected: file ends with a YAML-valid block (top-level key `codes:` mapping LOINC code → `{en, ja?}` dict).

- [ ] **Step 2: Append the 7 panel codes**

Add to `clinosim/codes/data/loinc.yaml` under the existing `codes:` mapping (alphabetical-by-code is fine but not required — match the file's existing convention):

```yaml
  "24325-3":
    en: "Hepatic function 2000 panel - Serum or Plasma"
    ja: "肝機能パネル"
  "24338-6":
    en: "Gas panel - Arterial blood"
    ja: "動脈血ガスパネル"
  "24356-8":
    en: "Urinalysis complete panel - Urine"
    ja: "尿検査パネル"
  "24373-3":
    en: "Activated partial thromboplastin time (aPTT) and Prothrombin time (PT)/INR panel - Platelet poor plasma"
    ja: "凝固検査パネル (PT/INR/APTT)"
  "51990-0":
    en: "Basic metabolic 2000 panel - Serum or Plasma"
    ja: "基本代謝パネル"
  "57698-3":
    en: "Lipid panel with direct LDL - Serum or Plasma"
    ja: "脂質パネル"
  "58410-2":
    en: "Complete blood count (hemogram) panel - Blood by Automated count"
    ja: "全血球計算パネル"
```

If any of these codes is already present in the file, leave the existing entry intact (first registration wins). The English text must match the Regenstrief LOINC display verbatim (preserve hyphens, capitalization, and punctuation exactly).

- [ ] **Step 3: Verify each code resolves**

```bash
python3 -c "
from clinosim.codes import lookup
for code in ['58410-2','51990-0','24325-3','57698-3','24373-3','24356-8','24338-6']:
    print(code, '->', lookup('loinc', code, 'en'))
"
```

Expected: 7 lines, each prints the code and the English display from Step 2 — none print the raw code (which would indicate a missed entry).

- [ ] **Step 4: Run the diagnosis-code-coverage test**

```bash
pytest tests/unit/test_diagnosis_code_coverage.py -q
```

Expected: PASS. (This is a coverage test for diagnosis codes; LOINC additions should not affect it, but run as a guardrail.)

- [ ] **Step 5: Commit**

```bash
git add clinosim/codes/data/loinc.yaml
git commit -m "$(cat <<'EOF'
feat(codes): add 7 LOINC panel codes for DiagnosticReport grouping

  58410-2  CBC panel
  51990-0  BMP panel
  24325-3  LFT panel
  57698-3  Lipid panel
  24373-3  Coag panel (PT/INR/APTT)
  24356-8  UA panel
  24338-6  ABG panel

English displays match Regenstrief LOINC verbatim; Japanese translations
added for JP locale. Used by the upcoming FHIR DiagnosticReport panel
grouping (see docs/superpowers/specs/2026-06-22-diagnostic-report-panels-design.md).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit succeeds.

---

### Task 2: Create the panel-group reference YAML

**Files:**
- Create: `clinosim/modules/output/reference_data/lab_panel_groups.yaml`

**Interfaces:**
- Consumes: nothing (data-only).
- Produces: `clinosim/modules/output/reference_data/lab_panel_groups.yaml` containing 7 panels with `loinc`, `display`, `components`, `min_components`, optional `skip_if_no_components_present`. Task 3 loads this file.

- [ ] **Step 1: Confirm the directory exists**

```bash
ls clinosim/modules/output/reference_data/ 2>&1 | head -5
```

Expected: the directory exists. If not, the user-config likely keeps reference data elsewhere — STOP and ask.

- [ ] **Step 2: Write the YAML**

Create `clinosim/modules/output/reference_data/lab_panel_groups.yaml`:

```yaml
# Lab panel groupings for FHIR DiagnosticReport.result[] assembly.
# Authoritative panel codes: LOINC (verified against Regenstrief, NLM
# clinicaltables.nlm.nih.gov). Components are the *canonical* clinosim
# analyte names (the same names that appear as lab_results.lab_name and as
# the keys in derive_lab_values output).
#
# Grouping priority order (high to low; resolves analyte dual-membership):
#   ABG > CBC > BMP > LFT > Lipid > Coag > UA

panels:
  ABG:
    loinc: "24338-6"
    display: "Gas panel - Arterial blood"
    components: [pH, pCO2, pO2, HCO3]
    min_components: 3

  CBC:
    loinc: "58410-2"
    display: "Complete blood count (hemogram) panel - Blood by Automated count"
    components: [WBC, Hb, Hct, Plt]
    min_components: 3

  BMP:
    loinc: "51990-0"
    display: "Basic metabolic 2000 panel - Serum or Plasma"
    components: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
    min_components: 5

  LFT:
    loinc: "24325-3"
    display: "Hepatic function 2000 panel - Serum or Plasma"
    components: [AST, ALT, ALP, T_Bil, Albumin, TP, GGT, LDH]
    min_components: 3

  Lipid:
    loinc: "57698-3"
    display: "Lipid panel with direct LDL - Serum or Plasma"
    components: [TC, LDL, HDL, TG]
    min_components: 3

  Coag:
    loinc: "24373-3"
    display: "Activated partial thromboplastin time (aPTT) and Prothrombin time (PT)/INR panel - Platelet poor plasma"
    components: [PT, PT_INR, APTT]
    min_components: 2

  UA:
    loinc: "24356-8"
    display: "Urinalysis complete panel - Urine"
    components: [Urine_pH, Urine_specific_gravity, Urine_protein, Urine_glucose, Urine_ketones, Urine_blood, Urine_nitrite, Urine_leukocyte_esterase]
    min_components: 3
    skip_if_no_components_present: true
```

Priority order (`ABG > CBC > BMP > LFT > Lipid > Coag > UA`) is YAML key order — the loader in Task 3 will iterate panels in YAML insertion order. PyYAML preserves insertion order on Python 3.7+ (`Loader=SafeLoader` returns a normal dict).

- [ ] **Step 3: Sanity-check the YAML loads**

```bash
python3 -c "
import yaml
with open('clinosim/modules/output/reference_data/lab_panel_groups.yaml') as f:
    d = yaml.safe_load(f)
panels = d['panels']
print('panels:', list(panels.keys()))
print('Coag components:', panels['Coag']['components'])
print('UA skip flag:', panels['UA'].get('skip_if_no_components_present'))
"
```

Expected:
```
panels: ['ABG', 'CBC', 'BMP', 'LFT', 'Lipid', 'Coag', 'UA']
Coag components: ['PT', 'PT_INR', 'APTT']
UA skip flag: True
```

- [ ] **Step 4: Commit**

```bash
git add clinosim/modules/output/reference_data/lab_panel_groups.yaml
git commit -m "$(cat <<'EOF'
feat(output): add lab panel reference YAML for DR grouping

7 panels (ABG/CBC/BMP/LFT/Lipid/Coag/UA) with LOINC codes, component
analyte names, and per-panel min_components thresholds. Priority order is
YAML key order; consumed by the upcoming _fhir_diagnostic_report builder.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit succeeds.

---

### Task 3: Implement the grouping logic (pure function) with TDD

**Files:**
- Create: `clinosim/modules/output/_fhir_diagnostic_report.py` (new module — grouping logic only, no FHIR resource building yet).
- Create: `tests/unit/test_diagnostic_report_panels.py` (new test file).

**Interfaces:**
- Consumes: panel YAML from Task 2; `clinosim.codes.lookup` for display resolution (only used in Task 4; not in Task 3).
- Produces:
  - `load_panel_groups() -> dict[str, dict]` — loads and caches the YAML; returns the `panels` mapping.
  - `_GroupedPanel = namedtuple("_GroupedPanel", ["panel_name", "bucket", "obs_refs"])` where `bucket` is `YYYY-MM-DDTHH:MM` and `obs_refs` is a list of Observation ids in YAML-component order.
  - `group_lab_orders(orders: list[dict], encounter_id: str) -> list[_GroupedPanel]` — pure function consuming the CIF orders list (filtered to lab orders with results), returning a deterministic list of grouped panels ordered by `(bucket, panel-priority)`.
- Task 4 calls `group_lab_orders` and `load_panel_groups` to build the DR FHIR resources.

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_diagnostic_report_panels.py`:

```python
"""Unit tests for DiagnosticReport panel grouping (post-hoc, AD-56 builder)."""
import pytest


@pytest.mark.unit
class TestLoadPanelGroups:
    def test_yaml_loads_with_all_seven_panels(self):
        from clinosim.modules.output._fhir_diagnostic_report import load_panel_groups
        panels = load_panel_groups()
        assert set(panels.keys()) == {"ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA"}

    def test_each_panel_has_loinc_components_threshold(self):
        from clinosim.modules.output._fhir_diagnostic_report import load_panel_groups
        for name, panel in load_panel_groups().items():
            assert "loinc" in panel and panel["loinc"]
            assert "display" in panel and panel["display"]
            assert isinstance(panel["components"], list) and panel["components"]
            assert isinstance(panel["min_components"], int) and panel["min_components"] >= 1

    def test_each_loinc_resolves_via_codes_lookup(self):
        from clinosim.codes import lookup
        from clinosim.modules.output._fhir_diagnostic_report import load_panel_groups
        for name, panel in load_panel_groups().items():
            disp = lookup("loinc", panel["loinc"], "en")
            assert disp and disp != panel["loinc"], (
                f"panel={name} loinc={panel['loinc']} did not resolve to a display"
            )


def _order(lab_name: str, when: str, idx: int) -> dict:
    """Build a minimal CIF-shaped lab order with one result, for grouping tests."""
    return {
        "order_type": "lab",
        "order_code": lab_name,
        "display_name": lab_name,
        "result": {"lab_name": lab_name, "value": 1.0, "result_datetime": when},
    }


@pytest.mark.unit
class TestGroupLabOrders:
    def test_cbc_full_panel_emits_one_group(self):
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
            _order("Plt", "2026-05-12T14:28:41", 3),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert len(groups) == 1
        g = groups[0]
        assert g.panel_name == "CBC"
        assert g.bucket == "2026-05-12T14:28"
        assert g.obs_refs == [
            "lab-ENC-001-0000", "lab-ENC-001-0001", "lab-ENC-001-0002", "lab-ENC-001-0003",
        ]

    def test_below_threshold_yields_no_group(self):
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        # CBC min_components = 3; only 2 components present
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T14:28:39", 1),
        ]
        assert group_lab_orders(orders, "ENC-001") == []

    def test_separate_minute_buckets_yield_separate_groups(self):
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
            # Same panel a minute later (e.g. q4-6h DKA draw) — should be a separate DR
            _order("WBC", "2026-05-12T14:29:38", 3),
            _order("Hb",  "2026-05-12T14:29:39", 4),
            _order("Hct", "2026-05-12T14:29:40", 5),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert len(groups) == 2
        assert {g.bucket for g in groups} == {"2026-05-12T14:28", "2026-05-12T14:29"}

    def test_abg_consumes_hco3_before_bmp(self):
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            # ABG components (priority 1)
            _order("pH",   "2026-05-12T14:28:00", 0),
            _order("pCO2", "2026-05-12T14:28:01", 1),
            _order("pO2",  "2026-05-12T14:28:02", 2),
            _order("HCO3", "2026-05-12T14:28:03", 3),
            # BMP components at the same minute (HCO3 must be consumed by ABG)
            _order("Na",         "2026-05-12T14:28:10", 4),
            _order("K",          "2026-05-12T14:28:11", 5),
            _order("Cl",         "2026-05-12T14:28:12", 6),
            _order("BUN",        "2026-05-12T14:28:13", 7),
            _order("Creatinine", "2026-05-12T14:28:14", 8),
            _order("Glucose",    "2026-05-12T14:28:15", 9),
            _order("Ca",         "2026-05-12T14:28:16", 10),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        panel_names = [g.panel_name for g in groups]
        # Both panels emit; ABG includes HCO3, BMP does NOT.
        assert "ABG" in panel_names
        assert "BMP" in panel_names
        abg = next(g for g in groups if g.panel_name == "ABG")
        bmp = next(g for g in groups if g.panel_name == "BMP")
        assert "lab-ENC-001-0003" in abg.obs_refs   # HCO3
        assert "lab-ENC-001-0003" not in bmp.obs_refs

    def test_solo_lab_yields_no_group(self):
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        orders = [
            _order("CRP", "2026-05-12T14:28:38", 0),
            _order("BNP", "2026-05-12T14:28:39", 1),
            _order("Troponin_I", "2026-05-12T14:28:40", 2),
            _order("HbA1c", "2026-05-12T14:28:41", 3),
        ]
        assert group_lab_orders(orders, "ENC-001") == []

    def test_ua_skip_when_no_components_present(self):
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        # UA panel has skip_if_no_components_present: true. With no UA analytes,
        # there should be no UA group emitted (vacuous-skip protection).
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert all(g.panel_name != "UA" for g in groups)

    def test_components_ordered_by_yaml_definition(self):
        """obs_refs in the group must follow the YAML's components order so the
        emitted FHIR result[] is stable across runs."""
        from clinosim.modules.output._fhir_diagnostic_report import group_lab_orders
        # Submit in REVERSE YAML order — grouping should still produce YAML order.
        orders = [
            _order("Plt", "2026-05-12T14:28:00", 0),
            _order("Hct", "2026-05-12T14:28:00", 1),
            _order("Hb",  "2026-05-12T14:28:00", 2),
            _order("WBC", "2026-05-12T14:28:00", 3),
        ]
        groups = group_lab_orders(orders, "ENC-001")
        assert len(groups) == 1
        g = groups[0]
        assert g.obs_refs == [
            "lab-ENC-001-0003",   # WBC (YAML order #1)
            "lab-ENC-001-0002",   # Hb
            "lab-ENC-001-0001",   # Hct
            "lab-ENC-001-0000",   # Plt
        ]
```

- [ ] **Step 2: Run the failing tests**

```bash
pytest tests/unit/test_diagnostic_report_panels.py -v
```

Expected: all tests FAIL with `ModuleNotFoundError: No module named 'clinosim.modules.output._fhir_diagnostic_report'`.

- [ ] **Step 3: Implement the module**

Create `clinosim/modules/output/_fhir_diagnostic_report.py`:

```python
"""FHIR DiagnosticReport panel grouping (AD-56 builder).

Post-hoc grouping of lab Observations into DiagnosticReport resources at
emit time. Pure function over the CIF orders list: no RNG, no CIF schema
read, no Observation-resource mutation. The bundle builder appends new
`dr-{panel}-{enc}-{seq}` DRs after the existing microbiology `dr-mb-*` DRs.

Spec: docs/superpowers/specs/2026-06-22-diagnostic-report-panels-design.md
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

import yaml


_PANEL_REF = Path(__file__).parent / "reference_data" / "lab_panel_groups.yaml"
_PANELS_CACHE: dict[str, dict] | None = None


def load_panel_groups() -> dict[str, dict]:
    """Return the panel definitions from lab_panel_groups.yaml (cached).

    Key order matches the YAML insertion order, which is the grouping
    priority (ABG > CBC > BMP > LFT > Lipid > Coag > UA).
    """
    global _PANELS_CACHE
    if _PANELS_CACHE is None:
        with open(_PANEL_REF) as f:
            data = yaml.safe_load(f) or {}
        _PANELS_CACHE = data.get("panels") or {}
    return _PANELS_CACHE


class _GroupedPanel(NamedTuple):
    panel_name: str
    bucket: str            # "YYYY-MM-DDTHH:MM"
    obs_refs: list[str]    # Observation ids in YAML-component order


def group_lab_orders(orders: list[dict], encounter_id: str) -> list[_GroupedPanel]:
    """Group lab orders into panel DiagnosticReport candidates.

    For each lab order with a result, derive (analyte_name, bucket, obs_id).
    Then per minute-bucket, iterate panels in priority order; for each
    panel collect any matching analyte that has not already been consumed
    by a higher-priority panel at the same bucket. If at least
    `min_components` are matched (and, when `skip_if_no_components_present`
    is set, at least one component was present), emit a _GroupedPanel.

    Returns groups sorted by (bucket ascending, panel-priority order).
    """
    panels = load_panel_groups()

    # Build: (bucket, lab_name) -> list of obs_ref (multiple draws same minute possible)
    # CIF emits one lab observation per order index; the FHIR Observation id is
    # `lab-{encounter_id}-{order_index:04d}`. Walk orders in their CIF order so
    # the index alignment matches what _fhir_observations.py emits.
    by_bucket: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for idx, order in enumerate(orders):
        if order.get("order_type") != "lab":
            continue
        result = order.get("result")
        if not result:
            continue
        when = (result.get("result_datetime") or "")[:16]
        if len(when) < 16:
            continue
        lab_name = result.get("lab_name") or order.get("display_name") or ""
        if not lab_name:
            continue
        obs_id = f"lab-{encounter_id}-{idx:04d}"
        by_bucket[when][lab_name].append(obs_id)

    groups: list[_GroupedPanel] = []
    for bucket in sorted(by_bucket.keys()):
        consumed: set[str] = set()
        for panel_name, panel in panels.items():
            components: list[str] = panel["components"]
            min_required: int = panel["min_components"]
            skip_if_empty: bool = bool(panel.get("skip_if_no_components_present"))

            present_count = 0
            obs_refs: list[str] = []
            for comp in components:
                refs = by_bucket[bucket].get(comp, [])
                # Pick the first not-yet-consumed obs_id for this analyte at this bucket
                for ref in refs:
                    if ref in consumed:
                        continue
                    obs_refs.append(ref)
                    consumed.add(ref)
                    present_count += 1
                    break
            if skip_if_empty and present_count == 0:
                continue
            if present_count < min_required:
                # Release any partially-consumed refs so a later panel could grab them
                # (the only case in practice: a panel below threshold doesn't block its
                # analytes from showing up in another panel — relevant for HCO3 in BMP
                # if ABG didn't reach threshold, etc.)
                for ref in obs_refs:
                    consumed.discard(ref)
                continue
            groups.append(_GroupedPanel(
                panel_name=panel_name, bucket=bucket, obs_refs=obs_refs,
            ))
    return groups
```

- [ ] **Step 4: Run the tests — expect all passing**

```bash
pytest tests/unit/test_diagnostic_report_panels.py -v
```

Expected: 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/output/_fhir_diagnostic_report.py tests/unit/test_diagnostic_report_panels.py
git commit -m "$(cat <<'EOF'
feat(output): grouping logic for DiagnosticReport panels (TDD)

New module clinosim/modules/output/_fhir_diagnostic_report.py with:
  - load_panel_groups()  (YAML loader, cached)
  - group_lab_orders(orders, encounter_id) -> list[_GroupedPanel]
    pure function returning (panel, bucket, [Observation-ref]) tuples
    in priority order. Time bucket = minute-resolution; analytes are
    consumed greedily by higher-priority panels at the same bucket.

Unit tests cover: YAML load, every LOINC resolves via codes.lookup,
full-panel grouping, below-threshold no-emit, separate-minute buckets,
ABG/BMP priority on shared HCO3, solo-lab pass-through, UA empty-skip,
component order matches YAML.

No FHIR resource construction yet — Task 4 wraps these tuples into
DiagnosticReport resources.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit succeeds.

---

### Task 4: Add the DR FHIR resource builder

**Files:**
- Modify: `clinosim/modules/output/_fhir_diagnostic_report.py` — append the FHIR resource builder.
- Modify: `tests/unit/test_diagnostic_report_panels.py` — append builder tests.

**Interfaces:**
- Consumes: `group_lab_orders` (Task 3); `clinosim.codes.lookup` for the panel display; `clinosim.codes.get_system_uri` for the LOINC system URI; `clinosim.codes.get_system_uri("hl7-service-category-v2-0074")` for the category coding (or the equivalent project helper — if absent, hard-code `"http://terminology.hl7.org/CodeSystem/v2-0074"` and add a `# TODO: factor system URI through get_system_uri`).
- Produces:
  - `build_dr_resource(group: _GroupedPanel, patient_id: str, encounter_id: str, country: str, performer_ref: str | None = None, issued: str | None = None) -> dict` — returns a single `DiagnosticReport` raw resource dict.
  - `build_lab_panel_reports(ctx) -> list[dict]` — bundle builder entry point matching the `Callable[[BundleContext], list[dict]]` signature.

- [ ] **Step 1: Append the failing FHIR-shape test**

Append to `tests/unit/test_diagnostic_report_panels.py`:

```python
@pytest.mark.unit
class TestBuildDrResource:
    def _group(self):
        from clinosim.modules.output._fhir_diagnostic_report import _GroupedPanel
        return _GroupedPanel(
            panel_name="CBC",
            bucket="2026-05-12T14:28",
            obs_refs=[
                "lab-ENC-001-0000", "lab-ENC-001-0001",
                "lab-ENC-001-0002", "lab-ENC-001-0003",
            ],
        )

    def test_shape_us(self):
        from clinosim.modules.output._fhir_diagnostic_report import build_dr_resource
        r = build_dr_resource(
            self._group(),
            patient_id="POP-000002", encounter_id="ENC-001",
            country="US", performer_ref="Practitioner/TECH-LAB-001",
            issued="2026-05-12T14:28:39",
            seq=0,
        )
        assert r["resourceType"] == "DiagnosticReport"
        assert r["id"] == "dr-cbc-ENC-001-0"
        assert r["status"] == "final"
        cat = r["category"][0]["coding"][0]
        assert cat["code"] == "LAB"
        coding = r["code"]["coding"][0]
        assert coding["system"] == "http://loinc.org"
        assert coding["code"] == "58410-2"
        # Display should be the LOINC English display
        assert "Complete blood count" in coding["display"]
        assert r["subject"] == {"reference": "Patient/POP-000002"}
        assert r["encounter"] == {"reference": "Encounter/ENC-001"}
        assert r["effectiveDateTime"] == "2026-05-12T14:28:00"
        assert r["issued"] == "2026-05-12T14:28:39"
        assert r["performer"] == [{"reference": "Practitioner/TECH-LAB-001"}]
        assert r["result"] == [
            {"reference": "Observation/lab-ENC-001-0000"},
            {"reference": "Observation/lab-ENC-001-0001"},
            {"reference": "Observation/lab-ENC-001-0002"},
            {"reference": "Observation/lab-ENC-001-0003"},
        ]

    def test_shape_jp_uses_japanese_display(self):
        from clinosim.modules.output._fhir_diagnostic_report import build_dr_resource
        r = build_dr_resource(
            self._group(),
            patient_id="POP-000002", encounter_id="ENC-001",
            country="JP", performer_ref=None, issued=None, seq=0,
        )
        coding = r["code"]["coding"][0]
        # JP locale should localize the LOINC display via codes.lookup("loinc",..,"ja")
        assert coding["display"] == "全血球計算パネル"
        # performer omitted when None
        assert "performer" not in r

    def test_seq_increments_per_call(self):
        from clinosim.modules.output._fhir_diagnostic_report import build_dr_resource
        r0 = build_dr_resource(
            self._group(), patient_id="P", encounter_id="E",
            country="US", performer_ref=None, issued=None, seq=0,
        )
        r1 = build_dr_resource(
            self._group()._replace(bucket="2026-05-12T15:00"),
            patient_id="P", encounter_id="E",
            country="US", performer_ref=None, issued=None, seq=1,
        )
        assert r0["id"] != r1["id"]
        assert r0["id"].endswith("-0")
        assert r1["id"].endswith("-1")
```

- [ ] **Step 2: Run the test — expect failures**

```bash
pytest tests/unit/test_diagnostic_report_panels.py::TestBuildDrResource -v
```

Expected: 3 tests FAIL with `ImportError: cannot import name 'build_dr_resource'`.

- [ ] **Step 3: Add the FHIR builder**

Append to `clinosim/modules/output/_fhir_diagnostic_report.py`:

```python
# ----------------------------------------------------------------------------
# FHIR resource construction
# ----------------------------------------------------------------------------

from clinosim.codes import lookup as _codes_lookup
from clinosim.codes import get_system_uri as _get_system_uri


_CATEGORY_LAB_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0074"


def build_dr_resource(
    group: _GroupedPanel,
    patient_id: str,
    encounter_id: str,
    country: str,
    performer_ref: str | None,
    issued: str | None,
    seq: int,
) -> dict:
    """Build a single FHIR DiagnosticReport resource for a grouped panel.

    Args:
      group: a _GroupedPanel from group_lab_orders().
      patient_id: CIF patient id (becomes Patient/{patient_id} subject).
      encounter_id: CIF encounter id (becomes Encounter/{encounter_id}).
      country: "US" or "JP" — selects English vs Japanese LOINC display.
      performer_ref: optional FHIR-shaped reference (e.g. "Practitioner/TECH-LAB-001").
      issued: optional ISO timestamp of report issuance; if None, omitted.
      seq: encounter-scoped sequence number for id uniqueness when the
        same panel emits at multiple draw-times.

    Returns: a raw FHIR resource dict (no Bundle envelope).
    """
    panels = load_panel_groups()
    panel = panels[group.panel_name]
    lang = "ja" if country == "JP" else "en"
    display = _codes_lookup("loinc", panel["loinc"], lang) or panel["display"]

    res: dict[str, object] = {
        "resourceType": "DiagnosticReport",
        "id": f"dr-{group.panel_name.lower()}-{encounter_id}-{seq}",
        "status": "final",
        "category": [{
            "coding": [{
                "system": _CATEGORY_LAB_SYSTEM,
                "code": "LAB",
                "display": "Laboratory",
            }],
        }],
        "code": {
            "coding": [{
                "system": _get_system_uri("loinc"),
                "code": panel["loinc"],
                "display": display,
            }],
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "effectiveDateTime": f"{group.bucket}:00",
        "result": [{"reference": f"Observation/{ref}"} for ref in group.obs_refs],
    }
    if issued:
        res["issued"] = issued
    if performer_ref:
        res["performer"] = [{"reference": performer_ref}]
    return res
```

- [ ] **Step 4: Run the tests — expect all passing**

```bash
pytest tests/unit/test_diagnostic_report_panels.py -v
```

Expected: 12 tests PASS (9 from Task 3 + 3 from Task 4).

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/output/_fhir_diagnostic_report.py tests/unit/test_diagnostic_report_panels.py
git commit -m "$(cat <<'EOF'
feat(output): build_dr_resource — DiagnosticReport panel FHIR shape

Adds build_dr_resource(group, patient_id, encounter_id, country,
performer_ref, issued, seq) producing a DiagnosticReport raw resource:
id `dr-{panel}-{enc}-{seq}`, category LAB (v2-0074), code LOINC panel
code with localized display, subject/encounter/result references, and
optional issued/performer. Result[] preserves YAML component order.
JP locale renders Japanese LOINC display via codes.lookup.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit succeeds.

---

### Task 5: Wire as a registered bundle builder

**Files:**
- Modify: `clinosim/modules/output/_fhir_diagnostic_report.py` — add `build_lab_panel_reports(ctx)`.
- Modify: `clinosim/modules/output/fhir_r4_adapter.py` — append the builder to `_BUNDLE_BUILDERS` (or register via `register_bundle_builder` at module import time).
- Modify: `tests/unit/test_diagnostic_report_panels.py` — append an end-to-end builder test using a hand-built `BundleContext`.

**Interfaces:**
- Consumes: `BundleContext` (from `clinosim.modules.output._fhir_observations`), `group_lab_orders`, `build_dr_resource`.
- Produces: `build_lab_panel_reports(ctx: BundleContext) -> list[dict]` registered in `_BUNDLE_BUILDERS` after `_bb_microbiology`.

- [ ] **Step 1: Verify the `BundleContext` field set**

```bash
grep -n "class BundleContext\|patient_id\|primary_enc_id\|country\|record\[" clinosim/modules/output/_fhir_observations.py | head -20
```

Expected: `BundleContext` defines `record`, `patient_id`, `country`, `primary_enc_id`, possibly `patient_sex`. This tells the builder how to look up the encounter id and country.

- [ ] **Step 2: Append the end-to-end builder test**

Append to `tests/unit/test_diagnostic_report_panels.py`:

```python
@pytest.mark.unit
class TestBuildLabPanelReports:
    def _ctx(self, orders, country="US"):
        from clinosim.modules.output._fhir_observations import BundleContext
        record = {
            "patient": {"patient_id": "POP-000002"},
            "orders": orders,
        }
        # The builder reads ctx.record, ctx.patient_id, ctx.primary_enc_id, ctx.country.
        # Construct a minimal ctx; fields not consumed by the DR builder can be defaults.
        return BundleContext(
            record=record, patient_id="POP-000002", country=country,
            primary_enc_id="ENC-001", patient_sex="F",
            roster_map={}, hospital_config={},
        )

    def test_cbc_panel_emits_one_dr(self):
        from clinosim.modules.output._fhir_diagnostic_report import build_lab_panel_reports
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
            _order("Plt", "2026-05-12T14:28:41", 3),
        ]
        out = build_lab_panel_reports(self._ctx(orders))
        assert len(out) == 1
        r = out[0]
        assert r["resourceType"] == "DiagnosticReport"
        assert r["id"] == "dr-cbc-ENC-001-0"
        assert len(r["result"]) == 4

    def test_no_lab_orders_yields_empty_list(self):
        from clinosim.modules.output._fhir_diagnostic_report import build_lab_panel_reports
        assert build_lab_panel_reports(self._ctx([])) == []

    def test_jp_locale_passes_through(self):
        from clinosim.modules.output._fhir_diagnostic_report import build_lab_panel_reports
        orders = [
            _order("WBC", "2026-05-12T14:28:38", 0),
            _order("Hb",  "2026-05-12T14:28:39", 1),
            _order("Hct", "2026-05-12T14:28:40", 2),
        ]
        out = build_lab_panel_reports(self._ctx(orders, country="JP"))
        assert len(out) == 1
        assert out[0]["code"]["coding"][0]["display"] == "全血球計算パネル"
```

If the `BundleContext` constructor signature in your codebase differs from the call above, adapt the test fixture — DO NOT change the BundleContext class for this PR.

- [ ] **Step 3: Run the test — expect failures**

```bash
pytest tests/unit/test_diagnostic_report_panels.py::TestBuildLabPanelReports -v
```

Expected: 3 tests FAIL with `ImportError: cannot import name 'build_lab_panel_reports'`.

- [ ] **Step 4: Implement `build_lab_panel_reports`**

Append to `clinosim/modules/output/_fhir_diagnostic_report.py`:

```python
def build_lab_panel_reports(ctx) -> list[dict]:
    """Bundle builder (AD-56): group ctx.record["orders"] into DR resources.

    Returns DRs in (bucket, panel-priority) order so the NDJSON output is
    stable across runs.
    """
    orders = ctx.record.get("orders", []) or []
    enc_id = ctx.primary_enc_id or ""
    if not enc_id:
        return []
    groups = group_lab_orders(orders, enc_id)
    # Sequence number per (panel) across buckets so ids stay unique.
    seq_by_panel: dict[str, int] = defaultdict(int)
    out: list[dict] = []
    for g in groups:
        seq = seq_by_panel[g.panel_name]
        seq_by_panel[g.panel_name] = seq + 1
        out.append(build_dr_resource(
            g, ctx.patient_id, enc_id, ctx.country,
            performer_ref=None, issued=None, seq=seq,
        ))
    return out
```

- [ ] **Step 5: Run the unit test — expect passing**

```bash
pytest tests/unit/test_diagnostic_report_panels.py::TestBuildLabPanelReports -v
```

Expected: 3 tests PASS.

- [ ] **Step 6: Register the builder in `fhir_r4_adapter.py`**

Edit `clinosim/modules/output/fhir_r4_adapter.py`. Find `_BUNDLE_BUILDERS` (around line 399) and append the new builder so it runs AFTER `_bb_microbiology` and after the other observation builders. The simplest placement is right after `_bb_microbiology`:

```python
from clinosim.modules.output._fhir_diagnostic_report import build_lab_panel_reports

_BUNDLE_BUILDERS: list[Callable[[BundleContext], list[dict]]] = [
    _bb_patient,
    _bb_coverage,
    _bb_encounters,
    _bb_conditions,
    _bb_allergies,
    _bb_occupation,
    _bb_labs,
    _bb_vitals,
    _bb_microbiology,
    build_lab_panel_reports,    # ← appended: panel DRs after the microbiology DRs
    _bb_medication_requests,
    _bb_medication_admins,
    _bb_procedures,
    _bb_practitioners,
    _build_nursing_observations,
    _build_immunizations,
    _build_family_history,
    _build_code_status,
    _build_smoking_status,
    _build_alcohol_use,
    _build_care_level,
]
```

(Adding `build_lab_panel_reports` AFTER `_bb_microbiology` means new DRs are appended to the DR stream after the microbiology DRs — preserves the byte-identical sub-invariant.)

- [ ] **Step 7: Verify with a tiny generate**

```bash
python -m clinosim.simulator.cli generate -p 50 -s 42 --country US -o /tmp/dr_smoke_us --format fhir 2>&1 | tail -3
wc -l /tmp/dr_smoke_us/fhir_r4/DiagnosticReport.ndjson
head -1 /tmp/dr_smoke_us/fhir_r4/DiagnosticReport.ndjson | python3 -c "import sys, json; d=json.loads(sys.stdin.read()); print('id=', d['id'], 'panel-code=', d['code']['coding'][0]['code'], 'n_results=', len(d.get('result',[])))"
```

Expected: `DiagnosticReport.ndjson` line count > 0 (new lab-panel DRs added on top of microbiology DRs from p=50). The first line's `id` should start with either `dr-mb-` (microbiology) or `dr-{panel}-` (one of cbc/bmp/lft/lipid/coag/abg).

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/output/_fhir_diagnostic_report.py \
        clinosim/modules/output/fhir_r4_adapter.py \
        tests/unit/test_diagnostic_report_panels.py
git commit -m "$(cat <<'EOF'
feat(output): wire DiagnosticReport panel builder into the FHIR adapter

build_lab_panel_reports(ctx) is appended to _BUNDLE_BUILDERS after
_bb_microbiology, so the NDJSON stream is:

  ...existing resources... DR(microbiology) DR(lab-panels) ...

End-to-end unit tests cover: CBC panel emits one DR with 4 results; empty
orders -> empty list; JP locale produces Japanese LOINC display.

The microbiology DR builder is untouched, so its records appear in
DiagnosticReport.ndjson byte-identically to master (the file just grows
with new dr-{panel}-* records).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit succeeds.

---

### Task 6: Full test suite

**Files:** none modified.

**Interfaces:**
- Consumes: branch HEAD with Tasks 1-5 applied.
- Produces: confidence that no integration / e2e test depended on `DiagnosticReport.ndjson` containing only microbiology records.

- [ ] **Step 1: Unit + integration**

```bash
pytest -m "unit or integration" --tb=short -q
```

Expected: ALL pass. The branch adds new tests (Task 3 + Task 4 + Task 5 = 15 new unit tests) on top of the master 484; aim for 499 passing.

- [ ] **Step 2: e2e**

```bash
pytest tests/e2e/ --tb=short -q
```

Expected: 39/39 pass. If any e2e fails because it counted `DiagnosticReport.ndjson` lines or asserted a specific DR id format, READ the assertion before patching:
- A line-count assertion is now wrong (DR count grew); update to a `>=` check rather than `==`.
- An assertion on `dr-mb-*` ids that no longer matches arrival order is a real regression — STOP and investigate.

- [ ] **Step 3: Commit (if any e2e assertion needed updating)**

If you needed to relax an e2e line-count assertion, commit it:

```bash
git add tests/e2e/<file>.py
git commit -m "$(cat <<'EOF'
test(e2e): allow DiagnosticReport.ndjson to grow with lab-panel DRs

The Task 5 wiring of build_lab_panel_reports appends new DRs to the
existing microbiology DR stream. e2e assertions that pinned the DR count
to the microbiology-only value are updated to a >= check.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

If no e2e needed updating, skip this step.

---

### Task 7: Byte-diff invariant gate

**Files:** none modified.

**Interfaces:**
- Consumes: branch HEAD with Tasks 1-6 applied.
- Produces: a recorded byte-diff report `/tmp/bytediff_dr_report.txt` consumed by Task 8's audit doc.

- [ ] **Step 1: Generate master baseline (US + JP, p=2000, seed 42)**

```bash
rm -rf /tmp/byte_master_us /tmp/byte_master_jp /tmp/byte_branch_us /tmp/byte_branch_jp
git stash -u -m "byte-diff baseline keep" || true
git checkout master
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US -o /tmp/byte_master_us --format cif fhir 2>&1 | tail -3
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP -o /tmp/byte_master_jp --format cif fhir --jp-insurance 2>&1 | tail -3
```

Expected: two output directories generated under `/tmp/`.

- [ ] **Step 2: Generate branch output**

```bash
git checkout feat/diagnostic-report-panels
git stash pop || true
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US -o /tmp/byte_branch_us --format cif fhir 2>&1 | tail -3
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP -o /tmp/byte_branch_jp --format cif fhir --jp-insurance 2>&1 | tail -3
```

Expected: matching output structure.

- [ ] **Step 3: Compare every NDJSON, with split treatment for `DiagnosticReport.ndjson`**

Write `/tmp/bytecheck_dr.py`:

```python
"""Byte-diff check for the DR-panel PR.

Rules:
  - Every NDJSON except DiagnosticReport.ndjson: must be byte-identical.
  - DiagnosticReport.ndjson: master records must appear as a byte-identical
    prefix (or equivalent matching subset) at the start of the branch file.
    The branch may append new dr-{panel}-* records after the dr-mb-* records.
"""
import hashlib, os, sys

def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def check(label, master_dir, branch_dir):
    print(f"=== {label} ===")
    files = sorted(os.listdir(f"{master_dir}/fhir_r4"))
    fail = 0
    for f in files:
        if not f.endswith(".ndjson"):
            continue
        m = md5(f"{master_dir}/fhir_r4/{f}")
        b = md5(f"{branch_dir}/fhir_r4/{f}")
        if m == b:
            print(f"  {f:40s} same")
            continue
        if f == "DiagnosticReport.ndjson":
            # Master records must be a prefix of branch records (line by line).
            with open(f"{master_dir}/fhir_r4/{f}") as fm:
                master_lines = fm.readlines()
            with open(f"{branch_dir}/fhir_r4/{f}") as fb:
                branch_lines = fb.readlines()
            if branch_lines[:len(master_lines)] == master_lines:
                added = len(branch_lines) - len(master_lines)
                print(f"  {f:40s} DIFFERS (expected): master {len(master_lines)} lines preserved, branch added {added} new DR records")
            else:
                print(f"  {f:40s} *** MICROBIOLOGY DR PREFIX BROKEN ***")
                fail += 1
        else:
            print(f"  {f:40s} *** UNEXPECTED DIFFERENCE ***")
            fail += 1
    return fail

fail = check("US", "/tmp/byte_master_us", "/tmp/byte_branch_us")
fail += check("JP", "/tmp/byte_master_jp", "/tmp/byte_branch_jp")
sys.exit(0 if fail == 0 else 1)
```

Run:

```bash
python3 /tmp/bytecheck_dr.py
echo "exit=$?"
```

Expected: exit 0; only `DiagnosticReport.ndjson` differs and the master prefix is preserved.

If ANY other file differs, STOP. The DR builder is leaking state somehow — re-read the registration in Task 5 Step 6 and confirm only `build_lab_panel_reports` was appended (no other builders reordered, no other resources mutated).

- [ ] **Step 4: Confirm patient and resource counts**

```bash
for d in /tmp/byte_master_us /tmp/byte_branch_us /tmp/byte_master_jp /tmp/byte_branch_jp; do
    echo "$d:"
    wc -l "$d/fhir_r4/Patient.ndjson" "$d/fhir_r4/Observation.ndjson" "$d/fhir_r4/DiagnosticReport.ndjson"
done
```

Expected: Patient count and Observation count identical between master and branch for US (and JP). DiagnosticReport count is higher in branch.

- [ ] **Step 5: Validate referential integrity of new DRs**

```bash
python3 - <<'PYEOF'
import json
# Build the Observation id set from the branch's Observation.ndjson, then check every
# DR's result[].reference resolves into that set.
for label, base in (("US", "/tmp/byte_branch_us"), ("JP", "/tmp/byte_branch_jp")):
    obs_ids = set()
    with open(f"{base}/fhir_r4/Observation.ndjson") as f:
        for line in f:
            obs_ids.add("Observation/" + json.loads(line)["id"])
    bad = []
    n_panel_dr = 0
    with open(f"{base}/fhir_r4/DiagnosticReport.ndjson") as f:
        for line in f:
            dr = json.loads(line)
            if dr["id"].startswith("dr-mb-"):
                continue
            n_panel_dr += 1
            for ref in dr.get("result", []):
                if ref["reference"] not in obs_ids:
                    bad.append((dr["id"], ref["reference"]))
    print(f"{label}: {n_panel_dr} panel DRs, {len(bad)} bad references")
    for dr_id, ref in bad[:5]:
        print(f"  {dr_id} -> {ref}")
PYEOF
```

Expected: each label prints `0 bad references`. If `bad` is non-zero, the obs id format in `build_lab_panel_reports` does not match the obs id format actually emitted by `_build_lab_observation`; fix the format in Task 5 step 4 and re-run.

- [ ] **Step 6: Save the byte-diff report**

```bash
{
  echo "byte-diff snapshot $(git log --oneline -1)";
  echo "";
  python3 /tmp/bytecheck_dr.py;
  echo "";
  echo "Patient / Observation / DR counts:";
  for d in /tmp/byte_master_us /tmp/byte_branch_us /tmp/byte_master_jp /tmp/byte_branch_jp; do
      echo "  $d:";
      wc -l "$d/fhir_r4/Patient.ndjson" "$d/fhir_r4/Observation.ndjson" "$d/fhir_r4/DiagnosticReport.ndjson"
  done
} > /tmp/bytediff_dr_report.txt
cat /tmp/bytediff_dr_report.txt
```

Expected: the report file is written and the cat output shows exit-0 byte-diff with all non-DR files identical and DR with master prefix preserved.

---

### Task 8: Audit + audit doc + PR

**Files:**
- Create: `docs/reviews/2026-06-22-diagnostic-report-panels-audit.md`

**Interfaces:**
- Consumes: branch HEAD; `/tmp/bytediff_dr_report.txt` from Task 7.
- Produces: audit doc documenting per-panel DR counts and integrity at production scale, committed to the branch; an open PR ready for review.

- [ ] **Step 1: Audit DR distribution at scale**

```bash
git checkout feat/diagnostic-report-panels
rm -rf /tmp/audit_branch_us /tmp/audit_branch_jp
python -m clinosim.simulator.cli generate -p 8000 -s 42 --country US -o /tmp/audit_branch_us --format fhir 2>&1 | tail -3
python -m clinosim.simulator.cli generate -p 4000 -s 42 --country JP -o /tmp/audit_branch_jp --format fhir --jp-insurance 2>&1 | tail -3
```

- [ ] **Step 2: Count DRs per panel**

```bash
python3 - <<'PYEOF' | tee /tmp/dr_panel_audit.txt
import json
from collections import Counter
for label, base in (("US p=8000", "/tmp/audit_branch_us"), ("JP p=4000", "/tmp/audit_branch_jp")):
    by_panel = Counter()
    n_results = []
    n_mb = 0
    with open(f"{base}/fhir_r4/DiagnosticReport.ndjson") as f:
        for line in f:
            dr = json.loads(line)
            if dr["id"].startswith("dr-mb-"):
                n_mb += 1
                continue
            panel = dr["id"].split("-")[1]
            by_panel[panel] += 1
            n_results.append(len(dr.get("result", [])))
    print(f"=== {label} ===")
    print(f"  microbiology DRs: {n_mb}")
    print(f"  panel DRs by code: {dict(by_panel.most_common())}")
    if n_results:
        n_results.sort()
        print(f"  result[] length percentiles: min={n_results[0]} p50={n_results[len(n_results)//2]} p90={n_results[len(n_results)*9//10]} max={n_results[-1]}")
PYEOF
```

Expected output style:
```
=== US p=8000 ===
  microbiology DRs: <existing audit number>
  panel DRs by code: {'cbc': <N>, 'bmp': <N>, 'lft': <N>, ...}
  result[] length percentiles: min=2 p50=... max=...
```

Sanity targets:
- `cbc` is the largest panel cohort (most admit workups order CBC).
- `bmp` is comparable to or larger than `cbc` (BMP often paired with CBC on admit).
- `abg` count > 0 (COPD/pneumonia/asthma/DKA encounters).
- `coag` count > 0 (DVT/PE/anticoag patients).
- `ua` count = 0 (UA components not present in this simulator version — the `skip_if_no_components_present` flag prevents emission).
- `lipid` count > 0 (outpatient lipid panels for E78 patients).

If `cbc=0` or `bmp=0`, the analyte naming in `lab_panel_groups.yaml` does not match what `derive_lab_values` emits as `lab_results.lab_name`. Inspect a CIF record's lab_results to find the actual analyte names and fix the YAML (preferred) rather than the engine — DO NOT change physiology engine analyte names for this PR.

- [ ] **Step 3: Write the audit doc**

Create `docs/reviews/2026-06-22-diagnostic-report-panels-audit.md` with the structure:

```markdown
# FHIR DiagnosticReport panel grouping — audit (2026-06-22)

## Summary

PR `feat/diagnostic-report-panels` adds post-hoc grouping of existing lab
Observations into FHIR `DiagnosticReport` resources (CBC / BMP / LFT / Lipid
/ Coag / UA / ABG). No CIF schema change, no observation-engine change.
Byte-diff at US `p=2000` + JP `p=2000` confirms every NDJSON except
`DiagnosticReport.ndjson` is byte-identical to master, and the existing
microbiology DR records appear as a byte-identical prefix in the branch's
`DiagnosticReport.ndjson`.

## Byte-diff invariant (gold criterion)

[paste contents of /tmp/bytediff_dr_report.txt]

## Panel DR distribution (US p=8000, JP p=4000)

[paste contents of /tmp/dr_panel_audit.txt]

### Interpretation

- CBC and BMP dominate, expected (admit panels).
- ABG present for respiratory/metabolic cohorts (COPD/pneumonia/asthma/DKA).
- Coag present for DVT/PE/anticoag patients.
- LFT and Lipid present for outpatient + hepatology workups.
- UA = 0 — UA component analytes are not yet emitted by the simulator. The
  YAML's `skip_if_no_components_present: true` correctly prevents an empty
  UA DR from being emitted. Adding UA analytes is a separate enhancement
  (`project_realism_gaps`).

## Referential integrity

Every panel-DR `result[]` reference resolves to an emitted Observation id in
the same export. Validated by `/tmp/bytecheck_dr.py` Step 5.

## Why no cascade

Spec ref: `docs/superpowers/specs/2026-06-22-diagnostic-report-panels-design.md`.
The grouping is a pure read of `ctx.record["orders"]` and produces a separate
list of `DiagnosticReport` resources. No state mutation, no RNG draws, no
CIF schema change. Every other resource type is byte-identical to master.

## Follow-ups

- UA component emission. Add urinalysis analytes to the observation engine
  (separate plan).
- DR `basedOn` to `ServiceRequest`. Requires emitting `ServiceRequest`
  resources for lab orders — out of scope for this PR.
- Order-aware grouping. Future CIF schema work that links lab_results to
  the panel-named order would replace the post-hoc time-bucket grouping
  with exact order-grouped emission. Tracked separately.
```

Fill in the placeholder paste sections with the actual content of the two `/tmp` files.

- [ ] **Step 4: Commit the audit doc**

```bash
git add docs/reviews/2026-06-22-diagnostic-report-panels-audit.md
git commit -m "$(cat <<'EOF'
docs(review): audit for FHIR DiagnosticReport panel grouping

Byte-diff invariant met at US p=2000 / JP p=2000 (only DiagnosticReport.ndjson
differs; microbiology DR prefix preserved byte-identically). Per-panel DR
counts at US p=8000 / JP p=4000 show CBC/BMP dominance, ABG/Coag presence
in the expected cohorts. UA correctly skipped (no components present).
Referential integrity: every DR.result[].reference resolves.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

- [ ] **Step 5: Push the branch and open the PR**

```bash
git push -u origin feat/diagnostic-report-panels
```

```bash
gh pr create --title "feat(output): FHIR DiagnosticReport panel grouping (CBC/BMP/LFT/Lipid/Coag/UA/ABG)" --body "$(cat <<'EOF'
## Summary

Group existing lab Observations into FHIR \`DiagnosticReport\` resources at
emit time, leaving every other NDJSON byte-identical to master and preserving
the existing microbiology DR emission unchanged.

- Post-hoc grouping at FHIR adapter build time (no CIF schema change).
- 7 panels: CBC, BMP, LFT, Lipid, Coag, UA, ABG — authoritative LOINC codes.
- AD-56 \`register_bundle_builder\` pattern; appended after \`_bb_microbiology\`.
- Pure function of \`ctx.record[\"orders\"]\` (no RNG, AD-16 preserved).

Spec: \`docs/superpowers/specs/2026-06-22-diagnostic-report-panels-design.md\`
Audit: \`docs/reviews/2026-06-22-diagnostic-report-panels-audit.md\`

## Changes

- \`clinosim/codes/data/loinc.yaml\` — 7 new LOINC panel codes (verified vs NLM Regenstrief).
- \`clinosim/modules/output/reference_data/lab_panel_groups.yaml\` — new panel definitions YAML.
- \`clinosim/modules/output/_fhir_diagnostic_report.py\` — new module:
  - \`load_panel_groups()\` cached YAML loader.
  - \`group_lab_orders(orders, encounter_id)\` pure grouping function.
  - \`build_dr_resource(...)\` FHIR shape builder (en/ja locale aware).
  - \`build_lab_panel_reports(ctx)\` bundle builder entry point.
- \`clinosim/modules/output/fhir_r4_adapter.py\` — register \`build_lab_panel_reports\` after \`_bb_microbiology\`.
- \`tests/unit/test_diagnostic_report_panels.py\` — 15 new unit tests covering YAML load, every LOINC resolves, grouping logic edge cases (priority order, time bucketing, threshold), FHIR resource shape, en/ja localization.

## Test plan

- [x] \`pytest -m \"unit or integration\"\` — all green (484 + 15 new = 499 expected)
- [x] \`pytest tests/e2e/\` — 39/39 green
- [x] Byte-diff invariant: only \`DiagnosticReport.ndjson\` differs at US p=2000 / JP p=2000 seed 42; microbiology DR prefix preserved.
- [x] Referential integrity: every panel-DR \`result[].reference\` resolves to an emitted Observation id (US p=2000, JP p=2000).
- [x] Audit (US p=8000 / JP p=4000): CBC/BMP dominant, ABG/Coag present in expected cohorts, UA correctly skipped.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: PR URL returned.

---

## Self-Review Notes

- **Spec coverage**: §1 → Task 1+Task 2; §2 → Task 3+Task 5; §3 → Task 4; §4 → Task 7; §5 → all tasks (no RNG anywhere). Verification §Unit → Tasks 3-5; Verification §Byte-diff → Task 7; Audit → Task 8.
- **Coefficient/value pin**: panel LOINCs `58410-2 / 51990-0 / 24325-3 / 57698-3 / 24373-3 / 24356-8 / 24338-6` appear identically in spec, YAML, and tests.
- **Type consistency**: `group_lab_orders` defined in Task 3 (returns `list[_GroupedPanel]`); consumed verbatim by `build_lab_panel_reports` in Task 5. `_GroupedPanel` is a `NamedTuple` so `._replace()` works (used in Task 4 Step 1 test).
- **Single risk** noted in the spec (id format mismatch between `build_lab_panel_reports` and `_build_lab_observation`) is operationalized in Task 7 Step 5 (referential integrity scan).
- **e2e flake guard**: Task 6 Step 2 explicitly notes how to read failures (line-count vs structural).
