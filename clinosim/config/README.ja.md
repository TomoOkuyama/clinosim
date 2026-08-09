# `clinosim.config` — 実行時設定 YAML

## 目的

`clinosim.config` は **YAML 専用の Python パッケージ**です:
`__init__.py` は空で、ディレクトリは import 隣接パスに実行時設定
ファイル群を配布するために存在します。YAML は病院容量 / 運用、国別
デフォルト、LLM プロバイダー設定を記述し、`clinosim.simulator` が
起動時に読み込みます。

これらのファイルは `clinosim` Python パッケージ内に配布されるため、
インストール済 wheel から `importlib.resources` 経由でアクセス可能
で、別のデータファイルパス指定は不要。

## スコープ

- **In scope**: 病院設定 YAML、国別デフォルト YAML、LLM サービス
  YAML。
- **Out of scope**: 参照臨床データ (`clinosim/modules/*/reference_data/`)、
  locale 固有データ (`clinosim/locale/`)、ユーザー作成データセット
  プリセット (repo ルート `datasets/`)。

## 公開 API

Python API なし。消費側は `importlib.resources` 経由、または
`clinosim.simulator.helpers` / `clinosim.types.config` のローダー
経由で YAML を読みます。

## 依存

なし。`__init__.py` は空。

## 定数と設定

### `hospital_operations.yaml` (デフォルト: 50 床コミュニティ病院)

患者の検査 / 画像 / 処置待ち時間を決定するリソース容量、スタッフ、
日次パターンを定義。別の病院形状シミュレーション時はコピーして調整。

主要トップレベルキー:

| キー | 目的 | 例 |
|---|---|---|
| `recommended_population` | デフォルト catchment 集団 (`US` / `JP` / `default`) | `40000` (US), `10000` (JP) |
| `imaging.wado_base_url` | 画像 Endpoint emission 用 WADO base URL | `https://pacs.…/dicomweb` |
| `resource_capacity` | analyser / scanner / OR / ED / 入院床 | `inpatient_beds: 50` |
| `staffing` | 看護 / 医師 / 薬剤スタッフ数 | (ファイル参照) |

### `hospital_small.yaml` / `hospital_large.yaml`

代替病院サイズ (50 床コミュニティ / 200 床地域中核)。スキーマは
`hospital_operations.yaml` と同じ。`clinosim generate --hospital-config`
で選択。

### `japan.yaml` / `us.yaml`

国別デフォルト上書き (encounter 構成、疾患有病率重み、保険パターン、
氏名 / 住所フォーマット)。

### `llm_service.yaml` / `llm_service.bedrock.yaml` / `llm_service.cloud.yaml`

ナラティブ生成用の LLM プロバイダー設定。プロバイダー詳細は
[`clinosim/modules/llm_service/` (English)](../modules/llm_service/README.md)
を参照 (日本語版は Issue #646 で作成予定)。

## ディレクトリ構成

```
clinosim/config/
  __init__.py           (空)
  hospital_operations.yaml   デフォルト 50 床コミュニティ病院
  hospital_small.yaml        50 床コミュニティ
  hospital_large.yaml        200 床地域中核
  japan.yaml                 JP 国別デフォルト
  us.yaml                    US 国別デフォルト
  llm_service.yaml           デフォルト LLM 設定
  llm_service.bedrock.yaml   AWS Bedrock 設定
  llm_service.cloud.yaml     クラウドホスト LLM 設定
```

## テスト

YAML はロード時に `clinosim.types.config` と `clinosim.simulator` が
検証。壊れた YAML は `SimulatorConfig` をインスタンス化するユニット
テストで失敗します。

```bash
pytest tests/unit -k config -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。
