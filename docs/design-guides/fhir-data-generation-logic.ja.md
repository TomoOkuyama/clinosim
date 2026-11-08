# FHIR Data Generation — Logic Design Guide

**Status:** Active(2026-06-29、PR1 ServiceRequest で確立)
**Audience:** clinosim FHIR resource builder を追加・拡張する新規開発者。正規レイアウト: builder は `clinosim/modules/output/fhir_r4/` 配下 (`conditions/` / `labs/` / `procedures/` / `documents/` 等の domain sub-package) にあり、`_BUNDLE_BUILDERS` registry と `register_bundle_builder()` は `clinosim/modules/output/fhir_r4/builder.py` で定義され `clinosim/modules/output/fhir_r4/__init__.py` から re-export される。
**Scope:** Layer 4 = FHIR R4 resource builder のみ。CIF 生成(Layers 1-3)は別 guide → [`docs/CONTRIBUTING-modules.md`](../CONTRIBUTING-modules.ja.md) を参照
**Binding spec:** コードマッピング・display 解決・多言語化は [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md) が規定する。本 guide と同 spec が食い違う場合は spec が優先する。

clinosim FHIR 生成は **CIF を入力として、FHIR R4 resource dict を出力する** thin な変換層。FHIR 仕様 / US Core / JP Core 準拠 / 多言語 display 解決 / identifier 規約 が中心の関心事。

CIF 側(Layers 1-3 = 参照 YAML、loader、CIF generation module)の design rule は既に [`docs/CONTRIBUTING-modules.md`](../CONTRIBUTING-modules.ja.md) に詳述されている(canonical path / `@lru_cache` 規約 / `_validate_*` 6-layer + 7-layer system defense / sub-seed / panel-aware grouping / etc.)。重複させない — 本 guide は **FHIR builder layer の責務だけ** を扱う。

第一巡読 = A → B → C → D 順。E は anti-pattern、F は参考 reference。

---

## A. FHIR builder layer の位置と責務

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

**FHIR builder の責務 / 非責務**:

| Layer 4 がする | Layer 4 がしない |
| --- | --- |
| CIF を読む(record / extensions / orders / lab_results / etc.) | CIF を変更する |
| `display(...) or <fallback>` で display 解決、コード付き concept は `dual_slot_concept()` で構築 | display 文字列を hardcode |
| `get_system_uri()` で system URI 解決 | system URI を hardcode |
| canonical constant(`SR_ID_PREFIX` 等)を **owner module から import** | constant を builder 内で再定義 |
| Layer 2 loader(`load_panel_definitions` 等)を import | builder 内で raw YAML を open |
| identifier system に `urn:clinosim:...` convention | private namespace を ad-hoc |
| FHIR R4 / US Core / JP Core 仕様準拠の resource shape | 仕様外 field を ad-hoc 追加 |

---

## B. 新規 FHIR resource を追加するには(How to)

### B.1 全体フロー(7 step)

| Step | 内容 | 関連 |
| --- | --- | --- |
| 1 | CIF 側で必要な field / extensions を準備(完了済み前提) | CIF guide = `docs/CONTRIBUTING-modules.md` |
| 2 | 新 builder file `clinosim/modules/output/fhir_r4/<domain>/<topic>.py` を作成 | Section B.2 |
| 3 | builder 内 canonical constants(ID prefix / identifier system)を定義 | Section B.3 |
| 4 | resource skeleton 関数を実装(`dual_slot_concept` / `display` / `get_system_uri` 経由) | Section B.4 |
| 5 | builder entry point `_bb_<topic>(ctx: BundleContext) -> list[dict]` を実装 | Section B.5 |
| 6 | `clinosim/modules/output/fhir_r4/builder.py:_BUNDLE_BUILDERS` に登録 OR `register_bundle_builder()` で追加 | Section B.6 |
| 7 | 単体 + integration テスト + audit lift_firing_proof を追加し、出力の変化を byte-diff で確認 | Section C |

### B.2 ファイル雛形

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
    lang = lang_for(ctx.country)   # canonical idiom — inline 分岐を書かない (E.10)
    res = {
        "resourceType": "<ResourceType>",
        "id": f"{TOPIC_ID_PREFIX}{item.id_field}",
        "identifier": [{
            "system": TOPIC_IDENTIFIER_SYSTEM,
            "value": item.id_field,
        }],
        "subject": {"reference": f"Patient/{ctx.patient_id}"},
        # コード付き concept: 英語専用 system (LOINC, SNOMED CT) は coding.display を英語のまま、
        # 日本語ラベルは .text に入れる (code-mapping spec §5.3)
        "code": dual_slot_concept("loinc", item.loinc_code, lang),
        # ... その他の display は display(...) or <明示 fallback>、system は get_system_uri()
    }
    # Encounter ref, requester, dates, code, category, etc. per the FHIR profile.
    return res
```

### B.3 canonical constants — 単一定義 site

builder 内に置く canonical constants(ID prefix、identifier system、category constants 等):

```python
# clinosim/modules/output/fhir_r4/<domain>/<topic>.py(writer = canonical owner)
TOPIC_ID_PREFIX = "tp-"                                       # FHIR Resource.id 接頭辞
TOPIC_IDENTIFIER_SYSTEM = "urn:clinosim:identifier:topic-id"  # identifier.system URI
TOPIC_CATEGORY_SNOMED = "..."                                 # category SNOMED code
```

これらを **audit module / consumer module / reader test** から import:

```python
# clinosim/modules/<owner>/audit.py(reader)
from clinosim.modules.output.fhir_r4.<domain>.<topic> import (
    TOPIC_ID_PREFIX, TOPIC_IDENTIFIER_SYSTEM,
)
```

**第三 consumer が出てきても、それも import する** — 再定義しない。

### B.4 display 解決 — `dual_slot_concept` と `display`

コード付き `CodeableConcept` は emit site で `dual_slot_concept`(`clinosim/modules/output/fhir_r4/lib/common.py`)により構築する。`text` slot を持たない `Coding` 型要素(`Encounter.class`)は `system_coding` を使う。いずれも code-mapping spec §5.3 の dual-slot 規則に従う: 英語専用 system(`is_english_only_system` — LOINC、SNOMED CT、HL7 terminology、DICOM、UCUM)では `coding.display` は全 locale で英語の正準 display のまま、日本語ラベルは `CodeableConcept.text` に入る。その他の system(JP Core、JP-CLINS、MEDIS、YJ、clinosim 独自)は出力言語の display を持つ。

```python
lang = lang_for(ctx.country)
code = dual_slot_concept("loinc", panel_loinc_code, lang, fallback_display=fallback_text)
# JP: {"coding": [{"system": "http://loinc.org", "code": ..., "display": <英語>}],
#      "text": <日本語ラベル>}
```

display 文字列だけが必要な場合は `clinosim.codes` の `display(...)` を明示 fallback 付きで呼ぶ(code-mapping spec §4.1、§9 — 新規コードで `lookup(...)` は使わない):

```python
icd_display = display("icd-10-cm", icd_code, lang) or ""
```

- 第一引数 = code system key(`"loinc"` / `"icd-10-cm"` / `"snomed-ct"` / `"rxnorm"` / `"jlac10"` / `"k-codes"` / `"cpt"` / etc.)
- 第三引数 = 出力言語。必ず `lang_for(ctx.country)`(`clinosim/countries.py`)で導出、inline 分岐禁止(E.10)
- 戻り値 = display string、不在時は `None`(`or` で fallback)
- code 自体を display として使うのは AD-30 違反 + 多言語破綻 = NG

**国によって code system 自体が変わる場合**(lab = JLAC10/LOINC、diagnosis = ICD-10/ICD-10-CM、drug = YJ/RxNorm、procedure = K-codes/CPT)は `clinosim.codes.system_key_for(kind, country)` で key を選択(共通ロジック統一 2026-07-02、single source of truth。未知の kind は `KeyError` で fail-loud):

```python
from clinosim.codes import system_key_for

system_key = system_key_for("lab", ctx.country)      # JP → "jlac10", 他 → "loinc"
concept = dual_slot_concept(system_key, code, lang_for(ctx.country))
```

system URI:

```python
sr["code"]["coding"][0]["system"] = get_system_uri("loinc")
```

- `get_system_uri("loinc")` → `"http://loinc.org"`
- `get_system_uri("snomed-ct")` → `"http://snomed.info/sct"`
- `get_system_uri("icd-10-cm")` → `"http://hl7.org/fhir/sid/icd-10-cm"`

文字列で hardcode しないこと。新規 system key は `codes/loader.py:_BUILTIN_URIS` に正準 HL7 URI を登録してから使用する(直近追加 2026-07-02: `hl7-endpoint-connection-type` / `hl7-endpoint-payload-type` / `hl7-subscriber-relationship`)。

### B.5 builder entry point + BundleContext interface

```python
def _bb_<topic>(ctx: BundleContext) -> list[dict]:
```

`BundleContext`(`clinosim/modules/output/fhir_r4/lib/context.py` 既存)は builder への uniform 入力:

| Field | 用途 |
| --- | --- |
| `ctx.record` | CIF 患者 record(dict-like、`record.orders` / `record.lab_results` / `record.extensions[X]` 等) |
| `ctx.country` | `"US"` / `"JP"` — 出力言語は `lang_for`、国ルールは `is_jp` / `is_us` に渡す |
| `ctx.patient_id` | `Patient/<id>` reference 解決 |
| `ctx.primary_enc_id` | primary encounter id |
| `ctx.roster_map` | staff roster lookup |
| `ctx.hospital_config` | hospital config(department, ward, etc.) |
| `ctx.is_readmission`, `ctx.prior_encounter_id` | readmission context |
| `ctx.primary_dx_code`, `ctx.admit_dx_code` | encounter dx codes |

builder は `ctx` の field しか触らない(global state なし、AD-16 維持)。

### B.6 builder の登録(AD-56)

**Built-in resource(near-essential / always-on)** = `_BUNDLE_BUILDERS` list に直接追加:

```python
# clinosim/modules/output/fhir_r4/builder.py
from clinosim.modules.output.fhir_r4.<domain>.<topic> import _bb_<topic>

_BUNDLE_BUILDERS: list[Callable[[BundleContext], list[dict]]] = [
    _bb_patient,
    # ... existing
    _bb_<topic>,   # ← 適切な emission 順序の位置に挿入
]
```

emission 順序の指針: **reference の解決順** に並べる。Patient → Encounter → Observation → ServiceRequest(observations の basedOn が指す)→ DiagnosticReport(observations を参照) は、ServiceRequest を Observation より前に置くと NDJSON 内 reference resolve が完全前方向。

**Opt-in module(AD-55 Module)** = `register_bundle_builder()` を import 時に呼ぶ:

```python
# clinosim/modules/<topic>/__init__.py or 起動 hook
from clinosim.modules.output.fhir_r4 import register_bundle_builder
from clinosim.modules.output.fhir_r4.<domain>.<topic> import _bb_<topic>
register_bundle_builder(_bb_<topic>)
```

`register_bundle_builder` は dedup あり(同名 builder の二重登録は無視)。

---

## C. テスト & 検証

### C.1 単体テスト(`pytest -m unit`)

builder 関数を直接呼ぶ。`BundleContext` を最小 fixture で構築:

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
    # LOINC は英語専用: coding.display は英語のまま、日本語ラベルは .text
    assert concept["coding"][0]["display"] == display("loinc", item.loinc_code, "en")
    assert concept["text"] == display("loinc", item.loinc_code, "ja")
```

### C.2 Integration test(`pytest -m integration`)

`run_beta` で小 cohort 生成 + NDJSON 検証:

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

`basedOn` 等の cross-resource reference は必ず integrity check。

### C.3 Determinism test(AD-16)

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

### C.4 audit module(★ silent-no-op gate、AD-60)

`clinosim/modules/<owner>/audit.py` に **lift_firing_proof** を追加(5+ equality_checks):

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

詳細 = `docs/CONTRIBUTING-modules.ja.md` § "3-axis DQR の実施手順"(AD-60 の `clinosim audit run` gate)参照。

### C.5 golden と byte-diff

リポジトリに FHIR NDJSON の golden は無い。新 resource は出力 NDJSON を変えるので、同じ seed の出力を PR の前後で byte-diff し、差分が意図したものだけであることを確認する。存在する golden は次の 2 つ:

- `tests/e2e/test_alpha_golden.py` — seed 42 の forced 患者 1 人の構造件数をテスト内に直接持つ。シミュレータの挙動を意図的に変えたときだけ更新する。
- `tests/fixtures/patient_profiles/*.golden.json`(と `*.llm-mock.golden.json`)— canonical patient profile の narrative golden(AD-66、`pytest -m regression`)。`clinosim regenerate-goldens` で再生成する。

詳細 = `docs/CONTRIBUTING-modules.md` § "PR 検証ガイド: byte-diff vs 3-axis DQR" 参照。

---

## D. 規約集(FHIR 固有)

### D.1 Resource.id naming 規約

| Resource | 形式 | 例 |
| --- | --- | --- |
| ServiceRequest(panel) | `sr-{encounter_id}-{panel_key}-{N}` | `sr-enc-pt001-001-CBC-1` |
| ServiceRequest(stand-alone) | `sr-{order_id}` | `sr-ORD-pt001-ADM-L05` |
| Observation(lab) | `lab-{encounter_id}-{seq}` | `lab-enc-pt001-001-0001` |
| Observation(vital sign) | `vs-{encounter_id}-{seq}` | `vs-enc-pt001-001-0001` |
| Observation(micro organism) | `mb-org-{...}` (MB_ORG_ID_PREFIX) | — |
| HAIEvent identifier | `hai-{enc}-{type}-{n}` | `hai-enc1-cauti-1` |

prefix は **canonical constant** として writer に置き、reader が import。

### D.2 identifier system URI 規約

```
urn:clinosim:identifier:<concept>      # 一般 internal identifier
urn:clinosim:placer-order-number       # ServiceRequest placerOrderNumber(PR1)
urn:clinosim:identifier:hai-event-id   # HAI culture cross-ref(PR3b-5)
urn:clinosim:staff                     # staff/practitioner internal id
```

新規 = 同 namespace で追加、定数化(`<TOPIC>_IDENTIFIER_SYSTEM` または `<TOPIC>_ID_SYSTEM`)。

### D.3 Multilingual coding(AD-46)

Condition / Procedure / ServiceRequest 等で **国の local code system + interop code system の dual coding**:

```python
"code": {
    "coding": [
        # Primary: 国の local code system (US = ICD-10-CM, JP = ICD-10 WHO + JP-K)
        system_coding(local_key, local_code, lang),
        # Interop: SNOMED CT は英語専用なので display は全 locale で英語
        system_coding("snomed-ct", snomed_code, lang),
    ],
    "text": short_clinical_name,   # 出力言語のラベル。never == code; never raw enum
}
```

各 coding は dual-slot 規則(code-mapping spec §5.3)に従い、出力言語のラベルは `text` に置く。

### D.4 JP localization 規約

出力言語は **`lang_for(ctx.country)`** で決める。**`is_jp(ctx.country)`** / **`is_us(ctx.country)`** は国ルール(診療報酬コード、profile、JP 専用 section)専用で、display の選択には使わない(code-mapping spec §5.1、§9)。3 つとも `clinosim/countries.py` にある。`ctx.country.lower() == "jp"` 等の hand-rolled 変種を書かない — E.10。JP cohort で:

- `text` / `name` field と、英語専用でない system(JP Core、JP-CLINS、MEDIS、YJ、clinosim 独自)の `coding.display` = 日本語(`dual_slot_concept` / `system_coding`、または `display(..., lang_for(ctx.country)) or <fallback>` 経由)
- 英語専用 system(LOINC、SNOMED CT、HL7 terminology、DICOM、UCUM)の `coding.display` = 英語。日本語ラベルは `dual_slot_concept` で `CodeableConcept.text` に入れる(code-mapping spec §5.3)。こうした coding 内の日本語 display は validation error
- 国依存の code system 選択(JLAC10 vs LOINC 等)= `system_key_for(kind, ctx.country)`(E.11)
- コード付き enum 値(category / priority / interpretation 等)= コードをキーにした `codes/data/hl7-*.yaml` registry を引く `dual_slot_concept()`(`clinosim/modules/output/fhir_r4/lib/common.py`)
- 薬剤 / 手技名 = code または catalog id を持つ場合は `display(...)`(catalog 薬剤は `drug_display`)、それ以外は lang-aware な free-text resolver `localize_drug_name(name, lang)`(`clinosim/locale/free_text.py`、`output/fhir_r4/lib/localization.py` から re-export)。wrapper は lookup table を持たない locale では no-op なので、`if lang == "ja":` gate 不要で単一 code path。基底 `_localize_drug_name` (country 引数版) は country seam 経由の caller 用に残存。いずれも canonical cached loader (`clinosim/locale/loaders/narrative.py:load_narrative_display_dict()` / `clinosim/locale/loaders/medical_display.py:load_med_terms_ja()`、両者とも B1/B2b 分割後 `clinosim/locale/loader.py` 経由で後方互換 re-export) — builder 内 raw YAML read 禁止 (E.3)。
- 診療科 display = `_dept_display()`(裏側は `load_department_display()`)
- 翻訳不在の場合 = en fallback + audit warn list

US cohort = 100% English、日本語文字 0 個。

### D.5 referenceRange + interpretation consistency(AD-47)

数値 Observation = `referenceRange` と `interpretation` を **必ず両方** emit、かつ **一貫**:

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

lab interpretation = value vs referenceRange から **再計算**(CIF の flag を盲信せず、output 時に整合性 verify)。

### D.6 Reference integrity

全 `reference` field は同 NDJSON export 内に解決:

```python
"subject": {"reference": f"Patient/{ctx.patient_id}"},
"encounter": {"reference": f"Encounter/{ctx.primary_enc_id}"},
"basedOn": [{"reference": f"ServiceRequest/{sr_id}"}],
```

dangling reference = audit `clinical` axis で fail-loud。

---

## E. Anti-patterns(FHIR builder layer)

### E.1 ❌ display 文字列の hardcode

```python
sr["code"]["coding"][0]["display"] = "Complete blood count (hemogram) panel..."  # NG
```

**Fix**: `dual_slot_concept("loinc", code, lang)` で concept を構築(文字列だけが必要なら `display("loinc", code, lang) or <fallback>`)。

### E.2 ❌ system URI の hardcode

```python
sr["code"]["coding"][0]["system"] = "http://loinc.org"  # NG
```

**Fix**: `get_system_uri("loinc")`。

### E.3 ❌ builder 内で raw YAML を open

```python
def _bb_foo(ctx):
    panels = yaml.safe_load(open(SOME_PATH))  # NG — Layer 4 が Layer 1 を直接読む
```

**Fix**: Layer 2 canonical loader を import(`from clinosim.modules.order.panel_grouping import load_panel_definitions`)。

**Precedent(共通ロジック統一 2026-07-02)**: `_fhir_localization.py`(現 `fhir_r4/lib/localization.py`)は locale の shared YAML(`med_terms_ja.yaml` / the retired `drug_names_ja.yaml` (deleted #1876; replaced by `load_narrative_display_dict` catalog UNION) / `department_display.yaml`)を builder 内 `yaml.safe_load` で inline 読みしていたが、`clinosim/locale/loaders/` の canonical cached loader(`medical_display.py:load_med_terms_ja()` / `narrative.py:load_narrative_display_dict()` / `medical_display.py:load_department_display()`、いずれも `clinosim/locale/loader.py` 経由で後方互換 re-export)に移設済。locale データが必要な builder はこれらを import する — 新たな inline YAML read を builder に書かない。cached loader の戻り値は共有 instance につき mutate 禁止。

### E.4 ❌ CIF に display 文字列を書き込む(AD-30 違反)

CIF generation の anti-pattern だが、FHIR builder から CIF を変更する誘惑も同じ:

```python
def _build_resource(item, ctx):
    item.display_name_ja = display(..., "ja")   # NG — CIF を書き換え
```

**Fix**: CIF は read-only で扱う。display 解決は builder の戻り値 dict 内で完結。

### E.5 ❌ ID prefix を文字列リテラルで埋める

```python
sr["id"] = f"sr-{order.order_id}"  # NG — "sr-" がリテラル
```

**Fix**: `SR_ID_PREFIX = "sr-"` 定数を import + `f"{SR_ID_PREFIX}{order.order_id}"`。

### E.6 ❌ 同じ display を 2 builder で再計算

```python
# fhir_r4/labs/observations.py
display_a = display("loinc", "58410-2", "ja")
# fhir_r4/labs/diagnostic_report.py
display_b = display("loinc", "58410-2", "ja")
```

技術的には問題ないが、もし display 加工(短縮 / 形式変換)が両 builder に必要なら共通 helper を `fhir_r4/lib/common.py` 等に抽出。

### E.7 ❌ Resource id collision に無頓着

```python
sr["id"] = f"sr-{enc}-{panel}-1"   # 同 encounter 内 panel 複数回でも 1 で固定 = collision
```

**Fix**: per-encounter counter で N を deterministically 算出(PR1 ServiceRequest `build_panel_counter` precedent)。

### E.8 ❌ 英語専用 coding に日本語、または `text` に日本語ラベルなし

```python
sr["code"]["coding"][0]["display"] = display("loinc", code, "ja")  # NG — LOINC は英語専用
sr["code"] = {"coding": [{"system": ..., "code": code,
                          "display": display("loinc", code, "en")}]}  # NG for JP — .text ラベルなし
```

**Fix**: `sr["code"] = dual_slot_concept("loinc", code, lang_for(ctx.country))` — `coding.display` は英語、日本語ラベルは `text`(code-mapping spec §5.3)。英語専用でない system では `dual_slot_concept` が出力言語の display を coding 自体に入れる。

### E.9 ❌ FHIR R4 spec 外の field を ad-hoc 追加

```python
sr["my_custom_field"] = "..."   # NG — Resource 内 free field 追加は spec 違反
```

**Fix**: spec 外データは `extension[]` array(FHIR R4 `Extension` element)に正規 URL で。

### E.10 ❌ hand-rolled な国判定 / 言語選択 idiom

```python
if ctx.country == "JP": ...                              # NG
if ctx.country.lower() == "jp": ...                      # NG
lang = "ja" if str(ctx.country).upper() == "JP" else "en"  # NG
```

**Fix**: `from clinosim.countries import is_jp, lang_for` — 出力言語には `lang_for(ctx.country)`、国ルールには `is_jp(ctx.country)` のみ使用。共通ロジック統一(2026-07-02)前は 5 種類の divergent idiom が混在し、case 正規化の差で JP gating が silent に外れる PR-90 class risk があった。両 helper が単一の正規化点(case-insensitive + strip)。

### E.11 ❌ 国→code system key の inline 選択

```python
system_key = "jlac10" if ctx.country == "JP" else "loinc"   # NG — inline 分岐
```

**Fix**: `from clinosim.codes import system_key_for` — `system_key_for("lab", ctx.country)`。kinds = `"lab"` / `"diagnosis"` / `"drug"` / `"procedure"`(jlac10/loinc、icd-10/icd-10-cm、yj/rxnorm、k-codes/cpt)。未知 kind は `KeyError` で fail-loud。選択 logic の single source of truth = `codes/loader.py:_COUNTRY_SYSTEM_KEYS`。

---

## F. Principles(深掘り reference)

### F.1 AD-30 — CIF は language-neutral

CIF は code のみ、display は output 時(= Layer 4 builder)に `display()` / `dual_slot_concept()` 経由で解決。**Why**: 言語追加 / locale 変更が `clinosim/codes/data/<system>.yaml` の `ja:` field 編集だけで完結、CIF / generation module への ripple ゼロ。

### F.2 AD-31 — FHIR resource id type-内 globally unique

各 resource type 内で id collision なし。canonical ID prefix(writer ↔ reader shared)+ encounter-scoped counter で deterministic。**Why**: NDJSON 出力後の任意 consumer が ref 解決可能。

### F.3 AD-46 — Multilingual coding

Condition / Procedure / ServiceRequest 等で dual coding(local primary + interop secondary)。**Why**: 国内 EHR と国際 interop の両立。

### F.4 AD-47 — referenceRange + interpretation consistency

数値 Observation の両 field を必ず両方 emit、output 時に再計算で整合性検証。**Why**: CIF の flag を盲信すると stale risk、output 時の独立計算で fresh 保証。

### F.5 AD-56 — register_bundle_builder

新 resource type は builder registry 経由で追加、`_build_bundle()` を編集しない。**Why**: 拡張点が one-point、新 resource 追加 PR が core simulator を触らない。

### F.6 AD-58 — register_output_adapter

新 output format(FHIR 以外 = HL7 v2 / CSV / etc.)も registry 経由、CLI `--format` dispatch を編集しない。**Why**: builder と adapter の両 dimension で拡張可能。

### F.7 Reference resolution invariant

全 `reference` field は同 NDJSON export 内に解決、dangling 不可。**Why**: PR-90 class silent-no-op の典型例(`basedOn` empty / dangling は audit gate なし → 黙って下流 NLP / EHR migration test を破壊)。

---

## 関連

- [`docs/CONTRIBUTING-modules.md`](../CONTRIBUTING-modules.ja.md) — CIF 生成側(Layers 1-3)の design rule 全集
- `DESIGN.md` — ADRs AD-17 / AD-25 / AD-30 / AD-31 / AD-46 / AD-47 / AD-55 / AD-56 / AD-58 / AD-59 / AD-60 / AD-61
- `AGENTS.md` — § "FHIR R4 output" / § "Common pitfalls" (`CLAUDE.md` は AGENTS.md への薄い pointer として残存)
- `.github/TEMPLATE_MODULE_README.md` — 新 module README boilerplate

## Application precedents(FHIR builder layer)

履歴の記録: ファイル名は各 PR 当時のもの。`_fhir_*.py` は現在 `clinosim/modules/output/fhir_r4/<domain>/` に移っており(例: `_fhir_localization.py` → `fhir_r4/lib/localization.py`)、下の `Composition.author` の TODO は解消済み(現在は `author_practitioner_id` から出力する)。

| PR | FHIR builder layer の wins |
| --- | --- |
| FA-1 (PR #49-#59) | 単一の FHIR adapter module を per-theme `_fhir_*` builder に分割(3015 行 → 498 行) |
| AD-46(Multilingual coding) | Condition / Procedure dual coding |
| AD-47(refRange + interpretation) | Observation 整合性 |
| PR-A 2026-06-26 | `_HERE / "reference_data"` canonical form を builder 側にも適用 |
| PR3b-5 (2026-06-29) | `HAI_EVENT_ID_SYSTEM` cross-module canonical URI(writer = `_fhir_microbiology.py`, reader = `clinosim/audit/axes/clinical.py`) |
| **PR1 ServiceRequest (2026-06-29)** | **`_fhir_service_request.py` builder + `SR_ID_PREFIX` / `PLACER_ORDER_NUMBER_SYSTEM` / `LAB_CATEGORY_*` canonical constants + `_fhir_observations.basedOn` + `_fhir_diagnostic_report.basedOn` + AD-61 ADR** |
| **Tier 1 #3 DocumentReference (2026-07-01)** | **`_fhir_document_reference.py`**: `DOC_REFERENCE_ID_PREFIX = "doc-"`, reads `ClinicalDocument.text` (base64-encode inline), `ClinicalDocument.loinc_code` → `type.coding[0].code`, `ClinicalDocument.format_type == "free_text"` gate; `_o()` dual-access on extensions dict; Patient + Encounter refs wired via `ctx.patient_id` / `ctx.primary_enc_id`. dict-path + dataclass-path tests required. |
| **Tier 1 #3 Composition (2026-07-01)** | **`_fhir_composition.py`**: `COMPOSITION_ID_PREFIX = "comp-"`, dispatched on `ClinicalDocument.format_type == "composition"`, reads `ClinicalDocument.sections` dict (NOT re-parses raw_text — ClinicalDocument.sections field is authoritative per AD-63 Task 8 fix), emits `section[]` with LOINC `title` + `text.div` per section key. `Composition.author = []` TODO pending practitioner ref wiring (α-min-2). |
| **Tier 1 #3 ClinicalImpression (2026-07-01)** | **`_fhir_clinical_impression.py`**: `CLINICAL_IMPRESSION_ID_PREFIX = "ci-"`, reads `extensions["clinical_impressions"]` list of `ClinicalImpressionRecord` (dataclass), `_o()` dual-access for dict path (production JSON-deserialized CIF), Patient + Encounter refs; `status = "completed"` for discharged encounters, `"in-progress"` for in-progress (AD-32 snapshot semantics). |
| **Tier 1 #3 AllergyIntolerance upgrade (2026-07-01)** | **`_fhir_allergy_intolerance.py`**: `ALLERGY_ID_PREFIX = "allergy-"`, reads `PersonRecord.allergies` (list[Allergy]). `code.coding[0]` = allergen SNOMED via `system_coding("snomed-ct", allergen_code, lang)` (全 locale で英語 display、日本語ラベルは `code.text`). `reaction[0].manifestation[0]` = reaction SNOMED. `criticality` / `category` / `clinicalStatus` / `verificationStatus` from `Allergy` dataclass fields. `_o()` dual-access for both Allergy dataclass (test fixture) and dict (production) paths required per CLAUDE.md rule. |
| **Tier 1 #3 document_chain audit (2026-07-01)** | **`clinosim/modules/document/audit.py`**: `ModuleAuditSpec` with `canonical_constants` (4 ID prefix constants), `lift_firing_proof` callable (17 equality_checks), `clinical_acceptance` (5-key dict per spec §9.3). Follows `imaging/audit.py` precedent exactly. `discover()` auto-registers on import. |
| **Tier 1 #3 α-min-2 CareTeam (2026-07-01)** | **`_fhir_care_team.py`**: `CARE_TEAM_ID_PREFIX = "ct-"`, 1:1 with encounter invariant, reads `extensions["nursing_assignment"]` (NursingAssignmentRecord dataclass), emits attending `participant[0]` (Practitioner ref via ctx.primary_attending_id) + nurse `participant[1]` (Practitioner ref from NursingAssignmentRecord.nurse_id). `subject = Patient/X`, `encounter = Encounter/Y`. `category[0]` = SNOMED 305048009 (Inpatient care team). `status = "active"` for in-progress / `"inactive"` for discharged encounters. AD-32: in-progress encounters emit CareTeam (no discharge gating needed). |
| **Tier 1 #3 α-min-2 ADMISSION_NURSING_ASSESSMENT (2026-07-01)** | **LOINC 78390-2** (corrected from 47420-5 per LOINC DB query), DocumentReference (`doc-`) + Composition (`comp-`) format. Emitted by `document` module enricher from `document_type_specs.yaml` `encounter_types_supported: [inpatient, icu, rehabilitation]` allowlist gate. Sections: chief_complaint, vital_signs, pain_assessment, skin_assessment, fall_risk (Morse scale score from nursing flowsheet), functional_status, care_plan. |
| **Tier 1 #3 α-min-2 NURSING_SHIFT_NOTE (2026-07-01; α-min-3 3-shift cadence 2026-07-02)** | **LOINC 34746-8**, `generation_frequency: daily_3shift` = 3 notes per LOS day (night 00:00 / day 08:00 / evening 16:00, chronological; `engine.SHIFT_SCHEDULE` canonical constant). `format_type: free_text` → emitted as DocumentReference (`doc-`) only; `document_id` carries a shift token suffix (`...-NN-night/day/evening`). Structural CIF stub stores the **neutral shift key** (`ClinicalDocument.shift`, AD-30 spirit); localized labels resolved at Stage 2 render time (en: night/day/evening, ja: 深夜/日勤/準夜). Same skip rules as `daily`: LOS=1 same-day skip + AD-32 in-progress los_days proxy. `encounter_types_supported: [inpatient, icu, rehab_inpatient]`. |
| **Tier 1 #3 α-min-2 NURSING_DISCHARGE_SUMMARY (2026-07-01)** | **LOINC 34745-0**, emitted only for discharged encounters (AD-32 snapshot gate: skipped when `encounter.status == "in-progress"`). DocumentReference + Composition. Sections: discharge_condition, patient_education, home_care_instructions, follow_up_plan. `discharge_once = True` gate in document enricher ensures exactly 1 per encounter. |
| **Tier 1 #3 α-min-2 OUTPATIENT_SOAP (2026-07-01)** | **LOINC 34131-3** (corrected from 11488-4 per LOINC DB query). `encounter_types_supported: [outpatient]`. Production wiring: outpatient.py calls `run_stage(POST_ENCOUNTER)` (α-min-2 Task 14 fix; verified 2026-07-02 — 1,841 Composition at US p=500 seed=42). |
| **Tier 1 #3 α-min-2 ED_NOTE + ED_TRIAGE_NOTE (2026-07-01)** | **ED_NOTE = LOINC 34878-9** (corrected from 51847-2), **ED_TRIAGE_NOTE = LOINC 54094-8** (corrected from 54094-8 confirmed correct). `encounter_types_supported: [emergency]`. Production wiring: emergency.py calls `run_stage(POST_ENCOUNTER)` (α-min-2 Task 14 fix; verified 2026-07-02 — ED_NOTE 210 Composition + ED_TRIAGE_NOTE 210 DocumentReference at US p=500 seed=42). |
| **Tier 1 #2 Imaging (2026-06-30)** | **New `_fhir_imaging_study.py` + `_fhir_endpoint.py` + polymorphic `_fhir_service_request.py` imaging dispatch + radiology `_fhir_diagnostic_report.py` variant + canonical constants `IMAGING_CATEGORY_SNOMED` / `DICOM_UID_SYSTEM` / `ENDPOINT_ID_PREFIX` / `DICOM_WADO_RS_CONNECTION_TYPE` / `IMAGING_SR_ID_PREFIX` + CIF→FHIR no-drop invariant (1:1 ImagingStudyRecord → ImagingStudy + Endpoint + radiology DR + imaging SR) + AD-62 ADR + `encounter_id` invariant (all orders in CIFPatientRecord.orders must have non-empty encounter_id before FHIR export — inpatient.py unknown-condition fix 2026-06-30)** |
| **Common-logic unification (2026-07-02)** | **`is_jp` / `lang_for`(現在は `clinosim/countries.py`)を JP 国判定 / 出力言語選択の唯一の正準 idiom として確立(5 divergent idiom を置換、E.10)+ `system_key_for(kind, country)`(`clinosim.codes`)= 国→code system 選択の single source of truth(E.11)+ `_fhir_localization.py` の 3 inline YAML loader を `clinosim/locale/loader.py` canonical cached loader へ移設(`load_med_terms_ja` / `load_narrative_display_dict` / `load_department_display`、E.3 precedent)+ `_BUILTIN_URIS` に `hl7-endpoint-connection-type` / `hl7-endpoint-payload-type` / `hl7-subscriber-relationship` 追加 + aggregate loader owner-module 移設(`load_all_disease_protocols` → `modules/disease/protocol.py`)+ protocol / config loader `@lru_cache` 化(shared instance = mutate 禁止)** |
