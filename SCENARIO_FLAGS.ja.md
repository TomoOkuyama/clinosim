# Scenario & Medication Flag

clinosim の `physiology.derive_lab_values()` は特定 lab 値を導出時に
持ち上げる boolean flag を受け付ける。本 doc は **全 flag の単一
情報源**、それらを配線する **helper アーキテクチャ**、および新規
flag 追加の **5-step process** を定義する。

## What are these?

Disease YAML が **scenario flag** (`causes_X`) を宣言し、患者
context が **medication flag** (`on_X`) を提供する。全 flag は
BNP-pattern surgical 原則 (AD-57) に従う: **`PhysiologicalState` を
mutate せず、formula-only の override**。state を immutable に保ち、
spec
`docs/history/specs-archive/2026-06-22-aki-dka-surgical-calibration-design.md`
に記載された master-RNG cascade defect を防ぐ。

## 現在の flag 一覧

| Flag | Type | Set in | Read in | Effect on lab values |
|---|---|---|---|---|
| `myocardial_injury` (alias: disease YAML 上の `causes_myocardial_injury`) | scenario | `acute_mi.yaml` | `physiology.engine.derive_lab_values` | Troponin_I → ACS-grade (~10-100 ng/mL); CK_MB も上昇 |
| `causes_vte` | scenario | `pulmonary_embolism.yaml`, `deep_vein_thrombosis.yaml`, `cerebral_infarction.yaml` (embolic) | `derive_lab_values` | D_dimer → VTE-positive (clamp 0.15-20 μg/mL FEU; PE/DVT/CI admit p50 ≥ 4) |
| `on_warfarin` | medication | `PatientProfile.current_medications` (慢性 AF / post-VTE) **または** 入院中 warfarin order で ≥ 3 日経過 (loading-dose ルール) | `derive_lab_values` | PT_INR → 治療域 2.5 + half-gain 併存疾患摂動、PT も同時 (PT = 12 × PT_INR) |
| `hai_inflammation_lift` | post-encounter (日次 loop flag ではない) | `hai` POST_ENCOUNTER enricher が populate する `extensions["hai"]` (Phase 3a) — CDC 重症度 proxy (clabsi/vap 0.35、cauti 0.20) × ramp factor (`min(1.0, days_since_onset / 2.0)`) | `derive_lab_values` (kwarg) | `effective_infl = min(1.0, infl + lift)` を CRP + WBC 公式にのみ流す。**Phase 3a は日次 loop の merge 経由で本 kwarg 付きで `derive_lab_values` を呼ばない**。代わりに `modules/hai/lab_lift.apply_hai_lab_lift` が日次 loop 後に closed-form 順方向 delta を直接 obs.value に適用する (noise + circadian を保存)。本 kwarg は `_hai_lift_delta` が公式を正確に mirror できるように存在する。 |

## Helper アーキテクチャ

`clinosim/modules/physiology/engine.py` に 2 兄弟 helper:

```python
def scenario_flags_from_protocol(protocol) -> dict[str, bool]:
    """disease YAML protocol から全 scenario flag を read。

    現在 {"myocardial_injury": bool, "causes_vte": bool} を返す。
    新 scenario flag 追加時は本 dict を拡張。"""
    ...

def medication_flags_from_context(patient, medication_orders=None,
                                  admission_date=None, current_day=None) -> dict[str, bool]:
    """患者 + encounter context から全 medication flag を read。

    現在 {"on_warfarin": bool} を返す。DOAC (apixaban / rivaroxaban
    / edoxaban / dabigatran) は意図的に **検出しない** — 臨床実務は
    DOAC の INR モニタリングをせず、DOAC の INR lift モデルは
    臨床的に誤解を招くため。新 medication coupling 追加時は本 dict
    を拡張。"""
    ...
```

以前存在した `hai_flags_from_record` helper は post-PR-90 xhigh
review pass (commit `4dd36a55`) で削除された: dead code (本番 caller
なし、自 unit test のみ) で、重複した event-walk logic + module
境界違反は投資に見合わなかった。順方向 delta path (下記) が正規の
Phase 3a 統合点。

**Call site での dict merge** (Phase 2b 4-site pattern、Phase 3a
以降も不変):

```python
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, all_med_orders, admission_date, day),
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, **flags)
```

**Phase 3a 順方向 delta path** (call-site merge とは別):

```python
# simulator/inpatient.py の日次 loop 後:
record = CIFPatientRecord(...)
run_stage(POST_ENCOUNTER, EnricherContext(config, master_seed, records=[record]))
apply_hai_lab_lift(record=record, encounter=encounter,
                   state_history=state_history, admission_time=admission_time)
```

`apply_hai_lab_lift` は内部で closed-form `_hai_lift_delta` を呼び
(`derive_lab_values` は呼ばない)、(HAI event × obs) ペアごとに
30+ analyte pipeline を再実行しないようにする。Phase 3b/c は同じ
順方向 delta pattern を再利用する — `antibiotic_flags_from_record`
等は Phase 3b coupling が日次 loop 可視性を本当に必要とする場合のみ
作り、先回りしない。

**4 つの `derive_lab_values` call site** (Phase 2b 以降すべて本
pattern を使用):

| Site | File | Purpose | medication context |
|---|---|---|---|
| Pass-1 lab loop | `simulator/inpatient.py:563-571` | 日次入院 labs | full (orders + day) |
| unknown-condition site | `simulator/inpatient.py:~1701` | unknown-condition encounter labs | chronic-only |
| ED admit | `simulator/emergency.py:126-130` | ED visit labs | chronic-only |
| Outpatient followup | `simulator/outpatient.py:152-160` | 慢性疾患 follow-up labs | chronic-only |

## 新 flag 追加 (5-step)

1. **種別を判別**:
   - Disease 駆動 (例: `causes_dehydration`) → **scenario flag** →
     `scenario_flags_from_protocol` を拡張。
   - 薬剤駆動 (例: `on_steroid`) → **medication flag** →
     `medication_flags_from_context` を拡張。
2. **flag を source で set**:
   - Scenario: 該当 disease YAML に `causes_X: true` を追加。
   - Medication: helper に検出 rule を追加 (`current_medications`
     や `medication_orders` に対する文字列 match)。
3. **helper の返却 dict** に新 key を追加。
4. **`derive_lab_values` に `<flag_name>: bool = False` kwarg** を追加。
5. **公式の変更を `derive_lab_values` に実装** (BNP-pattern surgical:
   state を mutate せず、公式のみ)。

**call site で `flag=value` を直接指定してはならない** — J5 防止 (
[AGENTS.md](AGENTS.md) 「AD-55 enricher patterns」参照)。helper が
単一 edit point であり、新 flag は `**flags` splat 経由で自動的に
4 site すべてに届く。

## DOAC 除外 (Phase 2b 臨床判断)

PT_INR について、DOAC 薬剤 (apixaban / rivaroxaban / edoxaban /
dabigatran) は `medication_flags_from_context` が意図的に **検出しない**。
臨床実務は DOAC の INR モニタリングをせず、DOAC INR lift のモデル化
は臨床的に誤解を招き、プロジェクトの「the true goal is FHIR / JP
Core compliance + 臨床整合」原則に反する。詳細は PR #82 (Phase 2b)。

## 関連

- [DESIGN.md](DESIGN.md) AD-57 (BNP-pattern surgical) / AD-59
  (per-order sub-rng) / AD-56 (enricher registry)
- [AGENTS.md](AGENTS.md) 「AD-55 enricher patterns」
- [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md)
  「PR 検証ガイド」+ 「sub-seed 導出ルール」
- [clinosim/modules/physiology/README.ja.md](clinosim/modules/physiology/README.ja.md)
  — helper API リファレンス
- spec / plan: `docs/history/specs-archive/2026-06-24-phase2a-vte-d-dimer-design.md`
  (causes_vte) + `docs/history/specs-archive/2026-06-24-phase2b-on-anticoagulation-design.md`
  (on_warfarin)

英語版: [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md)。
