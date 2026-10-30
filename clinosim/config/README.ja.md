# `clinosim.config` — 実行時設定 YAML

## 目的

`clinosim.config` は **YAML のみの Python パッケージ** です:
`__init__.py` は空で、ディレクトリの存在意義は import 隣接の安定した
パスに一連の実行時設定ファイルを配置することにあります。YAML は
病院キャパシティ・運用、国別デフォルト (US / JP)、LLM プロバイダ設定
を記述し、`clinosim.simulator` が起動時に読み込みます。

これらのファイルは `clinosim` Python パッケージ内部に同梱されるため、
インストール済 wheel からは `importlib.resources` で (またはソース
ツリーからは文字列パスで) データファイルパスを別途用意することなく
アクセス可能です。

## スコープ

- **In scope**: 病院設定 YAML、国別デフォルト YAML (`us.yaml` /
  `japan.yaml`)、LLM サービス YAML (base + プロバイダ別 override)。
- **Out of scope**: 参照臨床データ (`clinosim/modules/*/reference_data/`)、
  locale 固有データ (`clinosim/locale/`)、ユーザー作成データセット
  プリセット (repo-root `datasets/`)、リリース成果物設定
  (`pyproject.toml`)。

## 公開 API

Python API はありません。`__init__.py` は意図的に空。consumer は
それぞれのローダーで YAML を読みます:

- `hospital_*.yaml` — `clinosim.simulator._setup._load_hospital_ops`
  (`--hospital-config` の明示パス) または
  `clinosim.modules.facility.hospital_state.load_hospital_operations`
  (既定の `hospital_operations.yaml`)。いずれも
  `clinosim.simulator.hospital_ops.validate_hospital_ops` で検証。
- `japan.yaml` / `us.yaml` —
  `clinosim.modules.healthcare_system.loader.load_healthcare_config`
  → `clinosim.types.config.HealthcareSystemConfig`。
- `llm_service*.yaml` — `clinosim.simulator.cli_narrate` (または
  `--llm-config` の明示パス)。
- `determinism.yaml` — `clinosim.determinism`。

## 決定性

該当なし — 本パッケージは静的データを同梱するのみで実行時ロジックを
持ちません。YAML は consumer が遅延的にロードします。あるファイルの
バイト内容はロードのたびに同じインメモリ dict を生成します
(プロジェクトが用いる safe-loader サブセットについては YAML ライブ
ラリの決定性が保証されます)。

## 依存

パッケージレベルではなし。consumer 側で `pyyaml` を用意します。

## 定数と設定

### `hospital_operations.yaml` — デフォルト 50 床コミュニティ病院

検査・画像・処置の患者待ち時間を決めるリソースキャパシティ・スタッ
フ配置・日次パターンを定義。別の病院形状をシミュレートしたい場合は
コピーして調整。

主要トップレベルキー:

| キー | 目的 | 例 |
| --- | --- | --- |
| `recommended_population` | 国別のデフォルト catchment 人口 (`US` / `JP` / `default`) | `US: 40000`, `JP: 10000`, `default: 40000` |
| `imaging.wado_base_url` | 画像 Endpoint emit 用 WADO base URL | `https://wado.clinosim.example/dicomweb` |
| `available_departments` | この病院に存在する診療科 | `internal_medicine`, `cardiology`, … |
| `department_rollup` | 細分専門 → 存在する診療科へのマッピング | (ファイル参照) |
| `wards` / `ward_capacity` | 病棟定義と病棟別ベッド数 | (ファイル参照) |
| `resource_capacity` | 分析装置 / スキャナ / OR / ED / 入院ベッド | `inpatient_beds: 50`, `ed_beds: 8` |
| `staffing` | 看護師 / 医師 / 薬剤師人員 | (ファイル参照) |

### `hospital_small.yaml` / `hospital_large.yaml`

代替病院サイズ:

- `hospital_small.yaml` — 入院ベッド付き **10 床クリニック**、推奨
  catchment `12000`。外来中心 + たまに短期入院というシミュレーション
  向き。
- `hospital_large.yaml` — **200 床地域病院**、ED 20 床、推奨
  catchment `50000`。フルサービス
  教育・地域基幹形状。

いずれも `hospital_operations.yaml` と同じスキーマ。生成時に
`clinosim simulate --hospital-config <path>` で選択。

### `japan.yaml` / `us.yaml`

国別デフォルト overriding。それぞれ `country: "JP" | "US"` と国別の
臨床実践ノブを宣言:

- `lab_frequency_multiplier` (JP: 1.3、US: 0.8) — 国の実践パターンに
  合わせた per-day 検査オーダー率スケーリング。
- `discharge_criteria` (JP: `lab_normalization`、US:
  `functional_recovery`) — 退院エンジンが監視するゲート。
- `target_los_multiplier` (JP: 1.0、US: 0.35) — 国の典型的 LOS
  スケーリング。
- コードシステムデフォルト (診断: ICD-10-CM 対 ICD-10、薬剤:
  RxNorm 対 YJ、手技: CPT 対 K-codes)。

### `llm_service.yaml` とプロバイダ override

- `llm_service.yaml` — デフォルト LLM 設定。
- `llm_service.bedrock.yaml` — AWS Bedrock プロバイダ。
- `llm_service.sakura.yaml` — さくらインターネット GPU プロバイダ
  ([`docs/sakura_gpu_setup.md`](../../docs/sakura_gpu_setup.ja.md) 参照)。

LLM サービスがこれらのファイルを消費してプロバイダを切り替える方法は
[`clinosim/modules/llm_service/README.ja.md`](../modules/llm_service/README.ja.md)
参照。

## ディレクトリ構成

```
clinosim/config/
  __init__.py                   (意図的に空)
  determinism.yaml              超越関数精度 (mpmath prec) と RNG proxy
                                の設定 (詳細は clinosim/determinism.py)
  hospital_operations.yaml      デフォルト 50 床コミュニティ病院
  hospital_small.yaml           10 床クリニック
  hospital_large.yaml           200 床地域病院
  japan.yaml                    JP 国別デフォルト
  us.yaml                       US 国別デフォルト
  llm_service.yaml              デフォルト LLM 設定 (Ollama)
  llm_service.bedrock.yaml      AWS Bedrock プロバイダ
  llm_service.sakura.yaml       さくらインターネット GPU プロバイダ
```

## テスト

`tests/unit/test_hospital_config_completeness.py` が同梱の全
`hospital_*.yaml` の完全性・自己整合性を検査します。その他の YAML は
シミュレーションを走らせる全テストで間接的に走行します:
`hospital_*.yaml` はロード時に `validate_hospital_ops` で検査され、
国別 YAML は `HealthcareSystemConfig` にパースされます。壊れた YAML は
それらのテストが即座に失敗します。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.ja.md) 参照。

英語版: [`README.md`](README.md)。
