# PR 2 — Shared lab_coding_package loader: pre-cover contract verification

Date: 2026-07-25
Branch: `feat/lab-coding-package-pr2`
Baseline commit: `186ff8fa46` (master, post-PR 1)

## Purpose

Establish the shared `LabCodingPackage` loader that both the JP-CLINS lab
compliance axis and PR 3's CoreLabo emission strategy will consume.
The loader is a **pure SD/CS runtime view** — no clinosim IP crosses
into it, per session 67 memo (license boundary: clinosim's
analyte-name→slice-name mapping lives in PR 3's
`_lab_coding_strategy._slice_name_for_analyte`, not in the loader).

## Pre-cover 11-item contract confirmation

The session 67 memo required PR 2 to supply everything PR 3 needs, so
PR 3 does not have to add methods to the loader mid-chain. This section
maps each PR 3 requirement to the loader method that supplies it.

| PR 3 requirement | PR 2 loader supply | Verified by |
|---|---|---|
| analyte name → slice_name | (out of scope — PR 3 owns) | — |
| slice's Fixed display | `slice_info(slice_name).fixed_display` | `test_pkg_slice_info_k_has_expected_shape` |
| slice's 17-digit code candidates | `slice_info(slice_name).codes` | `test_pkg_slice_info_k_has_expected_shape` |
| 998-preferred method filter | `code.segments.method == "998"` | `test_pkg_slice_info_k_contains_998_methods` |
| material-match filter | `code.segments.material` | `test_code_segments_from_code_5_4_3_3_2_boundary` |
| specimen back-derivation | `code.segments.material` | (PR 3 consumes) |
| Fixed-display emit source | `slice.fixed_display` | (contract only, verified by axis) |
| LocalCode co-emit URI | `localcode_system_uri()` | `test_missing_package_localcode_uri_still_returned` |
| Uncoded fallback slice | `uncoded_slice()` | `test_pkg_uncoded_slice_spec_pinned_literals` |
| Uncoded Fixed emit values | `uncoded_slice().codes[0]` + `fixed_display` | `test_pkg_uncoded_slice_spec_pinned_literals` |
| axis Metric 2 display check | `all_slices_by_system_display()` | (axis migration test) |

**11/11 covered. PR 3 does not need to add anything to the loader.**

## Universal join key: (system, display)

The loader uses `(system_uri, display)` as the SD↔CS join key rather
than matching CS parent codes. This handles four SD slice names that
map non-trivially to CS parent codes:

- SD `abo-bld` → CS parent `BLD-ABO` (letter reversal)
- SD `rh-bld` → CS parent `BLD-Rh` (letter reversal)
- SD `u-ac` → CS parent `U-A/C` (contains slash)
- SD `u-pc` → CS parent `U-P/C` (contains slash)

Uniqueness of the join is guaranteed by the eCS profile itself — its
Open slicing discriminator is `value:system` + `value:display`, so
two slices sharing that pair would be ambiguous for the validator too.
`test_pkg_slice_info_abo_bld_bridges_reversed_cs_parent_code` pins
this bridge behavior.

## License boundary invariants

- **Loader supplies only SD/CS-derived data.** No clinosim-side name
  mapping, no bundled extract. The hotfix (PR #394) established this
  contract for the axis; PR 2 extends it to the shared loader that
  will also serve PR 3.
- **Uncoded slice values are spec-published literals** (`99999999999999999`
  + `未標準化コード項目(JLAC)`). These are copied into the loader as
  literals for the one Uncoded case — the SD carries these as Fixed
  values on the `unCoded` sub-elements, so this is a de-minimis copy
  of publicly published FHIR spec constants, not clinosim IP nor an
  adapted derivative of the CS.
- **`value_set_url` preserved verbatim** from SD, no version segment
  mangling. `test_pkg_value_set_url_preserved_verbatim` pins
  `|1.1.0a` suffix retention.

## byte-identical maintained

PR 2 touches only the axis + adds a new module; the emission path
(`_fhir_observations` + `_lab_coding_strategy`) is unchanged. Verified:

| cohort | Observation.ndjson SHA-256 (after PR 1) | after PR 2 | equal? |
|---|---|---|---|
| JP p=100 s=300 | `83933a25df4b9149a0e7460803096e15e3a83e22f518ac2206c8483f341bbfb8` | `83933a25df4b9149a0e7460803096e15e3a83e22f518ac2206c8483f341bbfb8` | ✅ |
| US p=100 s=300 | `ce6a9627296fbba7852a657870316573fce4ce72c4dea4dd4872e93e7a37778f` | `ce6a9627296fbba7852a657870316573fce4ce72c4dea4dd4872e93e7a37778f` | ✅ |

## axis migration: no compat shim

The axis's `_load_slice_map` and `_find_ecs_sd_path` were removed; the
axis now calls `load_lab_coding_package().all_slices_by_system_display()`
directly. Per session 67 memo: "旧 API を残さないと axis test が通らない
なら、それは axis が旧形状に暗黙依存していた" — the axis test suite
adapted to the new loader shape with a single-line monkeypatch change.
Both metrics still resolve to the same production values:

- CS 使用率: 0/2509 = 0.0% FAIL (unchanged from PR 1)
- Fixed display 一致率: 0/0 = n/a **N/A** (unchanged)
- 適用規則満足率: 0/2509 = 0.0% FAIL (unchanged)

## Verification

- `pytest tests/unit/`: 3,261 passed (+17 loader tests over PR 1's 3,244).
- `mypy --strict clinosim/modules/output/lab_coding_package.py clinosim/eval/axes/jp_clins_lab_compliance.py`: 0 errors.
- `ruff check` / `ruff format --check`: clean.
- byte-identical: JP + US SHA-256 identical to PR 1 output (see table above).
- axis 3-metric shape unchanged: 0/2509 FAIL / N/A / 0/2509 FAIL.
- Universal join bridge verified for 4 SD↔CS non-trivial name mappings
  (`abo-bld` case exercised in unit test).

## PR 3 handoff

PR 3 (`CoreLaboStrategy` real emit) can now be written against the
loader alone. Required additions in PR 3 (all in
`_lab_coding_strategy` / `_fhir_observations`, NOT in the loader):

- `_ANALYTE_TO_SLICE_NAME: dict[str, str]` — clinosim IP mapping
  (e.g. `{"WBC": "wbc", "K": "k", "Glucose_fasting": "fbg"}`).
- `_slice_name_for_analyte(lab_name) -> str | None` helper.
- `CoreLaboStrategy.emit_codings` replaces the LegacyJSLM delegation
  with:
  1. `slice_name = _slice_name_for_analyte(lab_name)` (clinosim IP)
  2. `info = pkg.slice_info(f"coreLaboJLAC10/{slice_name}")` (loader)
  3. Filter `info.codes` by method=998 first, then 999, then specific
  4. Filter further by material matching the analyte's canonical
     specimen (per PR 3's specimen mapping)
  5. Emit primary coding `(info.slice_system, chosen.code, info.fixed_display)`
- `CoreLaboStrategy.emit_localcode_coding` returns
  `(pkg.localcode_system_uri(), _internal_code, sanitized_designation)`
  with whitespace strip on display.
- `_classify_analyte` grows real logic; enum members already exist
  from PR 1.
- Uncoded strategy activation via `pkg.uncoded_slice()`.
- Character-class sanitize (LocalCode display whitespace strip) —
  helper lives in strategy module (per session 67 memo, generator-side
  vs validator-side split still deferred).

None of the above requires a new loader method. The loader can be
`frozen` after PR 2 (all subsequent additions are in strategy /
classifier code).
