# Authoritative code system snapshots

Machine-readable snapshots of authoritative code system displays used to
verify `clinosim/codes/data/*.yaml` against the original terminology sources.
These are **verification references**, not the source of truth — the source
of truth for what clinosim emits stays in `clinosim/codes/data/*.yaml`,
which allows small, deliberate clinical overrides (registered in the
allowlist below).

Companion documentation: [`docs/design-guides/code-display-authoritative-sync.md`](../../../docs/design-guides/code-display-authoritative-sync.md).

## Files

| File | Source | Fetched | Notes |
|---|---|---|---|
| `yj_tx_fragment.json` | `jpfhir-terminology 2.2606.0` / `CodeSystem-jp-medicationcodeyj-cs.json` (`http://capstandard.jp/iyaku.info/CodeSystem/YJ-code`) | 2026-07-19 | Fragment (2000 concepts on the tx-server), filtered to the 9 codes clinosim currently emits. |
| `loinc_2_82_tx.json` | LOINC 2.82 official master (`Loinc_2.82/LoincTable/Loinc.csv`) via `tx-server-build/loinc-src/` | 2026-07-19 | The LOINC codes clinosim emits; includes `display` (LONG_COMMON_NAME) + `short_display` (SHORTNAME) + `status`. Full display cross-check enabled in Issue #270 (Phase 3-b) — 75 legitimate shorthand + 17 tracked semantic-mismatch overrides registered in the allowlist. |
| `icd10_who_tx.json` | `fhir.tx.support.r4 0.37.0` / `CodeSystem-icd-10.json` (`http://hl7.org/fhir/sid/icd-10`, content `complete`) | 2026-07-19 | The WHO ICD-10 codes clinosim emits (`metadata.clinosim_codes_missing_from_source` counts the referenced codes absent upstream). |
| `icd10_mhlw_2013_ja.json` | MHLW 基本分類表 (ICD-10 2013年版準拠), `https://www.mhlw.go.jp/toukei/sippei/xls/kihon2013.xlsx` (sheet 基本分類表データ) | 2026-11-01 | Official Japanese names of the ICD-10 codes in `icd-10.yaml`; the `ja` field must equal them verbatim (Issue #2360). |
| `shinryo_koui_ssk_20261013_ja.json` | 社会保険診療報酬支払基金 基本マスター 医科診療行為マスター (`s_ALL20261013.csv`), `https://www.ssk.or.jp/seikyushiharai/tensuhyo/kihonmasta/kihonmasta_01.html` | 2026-11-01 | Master names of the codes registered in `k-codes.yaml` (keyed by 点数表区分番号 or 区分番号-枝番); each `ja` display must be one of them, or the 区分 name they start with (Issue #2340). |
| `rxnorm_rxnav_snapshot.json` | RxNav (NLM) `/REST/rxcui/{code}/historystatus` | 2026-10-28 | Status / name / term type for every RxCUI clinosim ships (`rxnorm.yaml`, `drugs.yaml`, US drug mapping); read offline by `tests/unit/codes/test_rxnorm_codes_name_their_drug.py`. |
| `yj_mhlw_snapshot.json` | MHLW drug-price list (薬価基準収載品目リスト, applied 2026-06-12), `https://www.mhlw.go.jp/topics/2026/04/xls/tp20260612-01_05.xlsx` | 2026-10-31 | MHLW ingredient and product names for the YJ codes of the drug catalog (`drugs.yaml` `codes.yj`); read offline by the JP drug-code tests (e.g. `tests/unit/codes/test_jp_yj_class_codes_name_their_drug.py`) (Issue #2347). A product the list carries under a generic-name (統一名収載) code is keyed by its MEDIS product code with the list's code in `mhlw_code` (Issue #3013). |
| `JP_MedicationCodeYJ_CS_full.json` | Full YJ-code CodeSystem (`http://capstandard.jp/iyaku.info/CodeSystem/YJ-code`, version `2026.8.31`, content `complete`) | — | 23,923 concepts; used by the YJ full-CS tests (e.g. `tests/unit/output/test_fhir_yj_full_cs_gate_1220.py`). |
| `snomed_allergy_tx.json` | tx.fhir.org R4 `CodeSystem/$lookup`, SNOMED CT International Edition 2025-02-01 | 2026-11-10 | The allergen substance, No Known Allergy and reaction manifestation codes of `allergens.yaml`, with display, FSN and `inactive`; read offline by `tests/unit/modules/allergy/test_allergen_codes_3128.py` (Issue #3128). |
| `jfagy_jpfhir_terminology.json` | `jpfhir-terminology 2.2606.0` (the JFAGY allergen CodeSystems in `JP_AllergyIntolerance_VS`; medication CodeSystems are fragments) | 2026-11-10 | The JFAGY codes JP AllergyIntolerance emits (`allergens.yaml` `country_codes.JP`), with the CodeSystem display each `ja` must equal (Issue #3128). |

Snapshot sizes follow clinosim's emit surface and grow with it, so they
are not listed above; count a snapshot's entries with
`len(json.load(open(path))["concept"])`.

Follow-on snapshots (SNOMED / MEDIS / BCP-47 etc.) are
tracked in the design guide and land in subsequent PRs as each Chain migrates
to the framework.

## Content mode: `fragment`

Every snapshot inherits its source CodeSystem's `content` semantics. When
`content == "fragment"`, codes NOT in the snapshot **may still be valid**
per the source terminology — the tx-server's loaded partial listing simply
doesn't have them. The cross-check test treats missing codes as *unable to
verify* (SKIP), not *invalid* (FAIL). The `metadata.clinosim_codes_missing_from_fragment`
field records exactly which clinosim codes are outside the fragment so a
future snapshot refresh can decide whether to widen the fetch.

## Cross-check semantics

For every `(system, code)` pair with an entry in the authoritative snapshot,
the cross-check test asserts that the clinosim-curated display matches
either:

- the authoritative `display` (preferred term), OR
- one of the authoritative `designation[].value` entries (synonyms), OR
- an entry in the override allowlist with a documented clinical rationale.

A drift (curated display ≠ authoritative AND not in allowlist) fails CI.
This is the 5th layer of the silent-no-op defense.

## Refresh workflow

1. Pull the latest `../fhir-jp-validator/tx-server-build/` (or the upstream
   terminology package).
2. Re-run the extraction script (per-code-system script in `scripts/`,
   TBD as each system migrates in).
3. Inspect the diff in the snapshot files.
4. For every changed entry:
   - Match now → curated data was already correct, no clinosim change needed.
   - Match now, curated stale → update `clinosim/codes/data/*.yaml`.
   - Deliberate divergence (clinical shorthand override) → add to allowlist
     with a clinical rationale.
5. PR: snapshot diff + allowlist / YAML edit + cross-check test refresh.

## What does NOT belong here

- Full CodeSystem definitions (structure, filters, hierarchies) — those live
  on the tx-server, not in clinosim.
- Locale translations that the authoritative source does not carry — those
  live in `clinosim/codes/data/*.yaml` under the `ja` / other-language keys
  and are considered clinosim-curated (not verifiable against upstream).
- Codes clinosim never emits — the fragment is intentionally scoped to
  clinosim's emit surface so the shipped snapshots stay small.
