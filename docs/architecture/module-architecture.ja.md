<!-- README.md から抽出 (Issue #568 PR A)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# モジュールアーキテクチャ

> **注:** 以下のフォルダマップは概念構造を示すもので、コード数や
> 詳細ファイルリストの一部は執筆時点のスナップショットです。canonical
> なモジュール一覧・数は [`../../MODULES.md`](../../MODULES.md)、
> 各コード数の現在値は
> [`../../clinosim/codes/README.md`](../../clinosim/codes/README.md)
> 参照。

```
clinosim/
├── codes/                    # ★ 国際コードシステム + 多言語 display (locale 非依存)
│   ├── data/                 # 32 YAML (icd-10-cm / icd-10 / loinc / jlac10 /
│   │                         #          rxnorm / yj / cpt / k-codes / snomed-ct /
│   │                         #          hot7 / cvx / HL7 terminology / JP-CLINS eCS 等)
│   └── loader.py             # lookup(system, code, lang) API
│
├── locale/                   # 国/文化固有データ
│   ├── jp/, us/
│   │   ├── names.yaml        # 氏名 (姓 + 名 + 読み)
│   │   ├── addresses.yaml    # 47 都道府県 / 50 州 + ZIP
│   │   ├── demographics.yaml # 年齢分布、incidence
│   │   ├── formatting.yaml   # 日付/単位フォーマット
│   │   ├── reference_range_lab.yaml  # JCCLS / Tietz 基準範囲
│   │   └── code_mapping_*.yaml  # 内部検査名 → 標準コード
│   └── shared/
│       ├── chronic_followup.yaml      # 慢性疾患別外来パターン
│       ├── chronic_medications.yaml   # 家庭薬 + monitoring
│       └── naming_rules.yaml          # 氏名生成規則
│
├── config/                   # 病院設定 YAML
│   ├── hospital_operations.yaml  # 50 床コミュニティ病院 (デフォルト)
│   ├── hospital_small.yaml       # 10 床クリニック
│   ├── hospital_large.yaml       # 200 床地域病院
│   ├── llm_service.yaml          # LLM (ローカル Ollama デフォルト)
│   ├── llm_service.bedrock.yaml  # AWS Bedrock
│   ├── llm_service.cloud.yaml    # Anthropic API
│   └── llm_service.sakura.yaml   # Sakura Cloud Ollama
│
├── types/                    # データ型定義 (Pydantic / dataclass)
│   ├── config.py             # SimulatorConfig
│   ├── patient.py            # PatientProfile, ChronicCondition
│   ├── clinical.py           # PhysiologicalState (14 変数), ClinicalDiagnosis
│   ├── encounter.py          # Encounter, Order, VitalSignRecord, MAR
│   ├── identity.py           # NationalIdentity, InsuranceEnrollment, IdentityTimeline
│   └── output.py             # CIFDataset, CIFPatientRecord, CIFMetadata
│
├── modules/                  # 機能モジュール (33 パッケージ、各 README 有)
│   ├── disease/              # 疾患 YAML プロトコル
│   ├── encounter/            # 46 ED/外来症例 YAML
│   ├── physiology/           # 14 状態モデル + lab/vital 導出
│   ├── clinical_course/      # 6 archetype + 合併症 + 診断フィードバック
│   ├── diagnosis/            # ベイジアン鑑別 (LR table)
│   ├── observation/          # 3 層 lab noise + フラグ
│   ├── order/                # Lab/薬剤/画像オーダー + 結果遅延
│   ├── procedure/            # 手術 + ベッドサイド + リハビリ
│   ├── population/           # 集団/世帯生成 + ライフイベント
│   ├── patient/              # Layer1 → Layer2 activator
│   ├── staff/                # 病院スタッフ roster + 割り当て
│   ├── facility/             # 病院 state + M/M/1 queueing
│   ├── healthcare_system/    # 国別パラメータ (JP / US)
│   ├── identity/             # 住民識別子 & 保険番号 (JP、opt-in)
│   ├── output/               # CIF / FHIR R4 / CSV + 臨床文書
│   │   ├── cif_writer.py              # CIF structural writer
│   │   ├── fhir_r4_adapter.py         # FHIR R4 Bulk NDJSON (DocumentReference 含む)
│   │   ├── csv_adapter.py             # CSV テーブル
│   │   └── hospital_course_extractor.py  # ★ 決定的イベント抽出
│   ├── llm_service/          # LLM アクセス全部 (AD-11)
│   │   ├── engine.py                  # LLMService, LLMTaskType, PatientSummary
│   │   ├── factory.py                 # YAML → LLMService
│   │   ├── prompt_registry.py         # ★ YAML ベースプロンプトテンプレート
│   │   ├── cache.py                   # ★ SHA256 disk cache
│   │   ├── providers/                 # ★ プラグ可能 provider サブパッケージ
│   │   │   ├── base.py                # LLMProvider Protocol + ProviderResponse
│   │   │   ├── ollama.py              # ローカル Ollama
│   │   │   ├── bedrock.py             # AWS Bedrock (boto3 遅延 import)
│   │   │   └── mock.py                # 決定的テスト provider
│   │   └── prompts/                   # ★ プロンプトテンプレート YAML tree
│   │       └── en/                    # 英語プロンプト (17 テンプレート —
│   │           │                      #   入院時 H&P、退院・死亡サマリ、
│   │           │                      #   手術・処置ノート、紹介状、
│   │           │                      #   死亡証明書 contributing +
│   │           │                      #   duration、死亡退院サマリの
│   │           │                      #   section 別断片、
│   │           │                      #   narrative_seed + bundle)
│   │           ├── admission_hp.yaml
│   │           ├── discharge_summary.yaml
│   │           ├── death_summary.yaml
│   │           ├── operative_note.yaml
│   │           ├── procedure_note.yaml
│   │           ├── referral_note.yaml
│   │           └── … (clinosim/modules/llm_service/prompts/en/ 参照)
│   └── validator/            # 公開ベンチマークとの比較
│
├── simulator/                # トップレベルオーケストレーション
│   ├── engine.py             # run_beta, run_forced
│   ├── inpatient.py          # 入院シミュレーション
│   ├── emergency.py          # ED 訪問
│   ├── outpatient.py         # 外来訪問
│   ├── helpers.py            # Ward/department resolver、mortality 等
│   └── cli.py                # CLI エントリ (simulate/generate、narrate、export-fhir、…)
│
└── tests/
    ├── unit/                 # モジュール単体テスト
    ├── integration/          # cross-module 統合テスト
    └── e2e/                  # E2E + golden ファイルテスト
```

各モジュールは **README.md** を持ち、目的・設計原則・API・データ
構造・拡張手順を文書化。

---
