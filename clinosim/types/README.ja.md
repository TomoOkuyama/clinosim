# `clinosim.types` — 共有データ型 (dataclasses)

## 目的

`clinosim.types` はプロジェクト全体で使用する `@dataclass` / `StrEnum`
/ `typing.TypedDict` 定義を集約します。ドメイン別分割 (AD-18) により
ファイルサイズを管理可能にし、cross-module import を自明化します:
`from clinosim.types.encounter import Encounter` は巨大なトップレベル
モジュールより可読性が高い。

`clinosim.types` は **純粋なデータ形状パッケージ** — `__post_init__`
の正規化以外に実行時ロジックは持ちません。型のフィールドを変更する
コードは所有 module (`simulator/` / `modules/*/` / `output/`) に属し、
本パッケージには置きません。

## スコープ

- **In scope**: 中核的な臨床・運用・設定型のための dataclass /
  StrEnum / TypedDict / Protocol 定義、および `__post_init__` 正規化。
- **Out of scope**: 単純な正規化を超えてフィールドを読み書き・変更する
  コード。ビジネスロジックは `simulator/` と `modules/*/` に属します。

## 公開 API

`clinosim/types/__init__.py` は各サブモジュールの公開名を
`from clinosim.types.<domain> import *` で再エクスポートするので、
呼び出し側は以下いずれかが可能:

```python
from clinosim.types.encounter import Encounter
# または:
from clinosim.types import Encounter          # 便宜的な再エクスポート
```

### サブモジュール (ドメイン別)

| サブモジュール | 内容 |
|---|---|
| `clinical.py` | 臨床イベント中核型 (文書、所見) |
| `config.py` | `SimulatorConfig` と関連する実行時設定モデル |
| `encounter.py` | `Encounter` / `EncounterType` / `EncounterStatus` / order / 薬剤投与 |
| `identity.py` | `PatientProfile` 識別子、JP マイナンバー / 保険型 |
| `microbiology.py` | 培養 / 感受性型 |
| `output.py` | コホートレベル出力メタデータ |
| `patient.py` | `PatientProfile` / `BaselineVitals` / 慢性疾患型 |
| `population.py` | 集団生成の中間型 |
| `procedure.py` | 手術・治療手技型 |
| `staff.py` | スタッフ・医療者型 |
| `allergy.py` | `Allergy` / `AllergyReaction` |
| `device.py` | 医療機器型 |
| `diagnosis.py` | 診断イベント型 |
| `document.py` | 文書・ナラティブ型 |
| `family_history.py` | 家族歴型 |
| `hai.py` | 医療関連感染型 |
| `imaging.py` | 画像検査・レポート型 |
| `triage.py` | ED トリアージ型 |

## 依存

- 標準ライブラリの `dataclasses` / `enum` / `datetime` / `typing`。
- `typing_extensions` (旧 Python 互換 import のみ)。
- **他の `clinosim.*` モジュールへの依存なし**。types は依存グラフの
  最下層。

## 定数と設定

- Sentinel 値 `_UNSET_DATETIME = datetime(1970, 1, 1)` と
  `_UNSET_DATE = date(1970, 1, 1)` — 決定性根拠は `clinical.py` の
  ブロックレベルコメント (2026-07-04) を参照。これらの sentinel は
  private (先頭アンダースコア) で、`None` だと下流のシリアライズを
  壊す optional field のデフォルトにのみ使用。
- StrEnum 値 (例: `EncounterType.INPATIENT = "inpatient"`) は
  FHIR / CIF output builder が消費する wire-level 文字列値。StrEnum
  値の変更は wire-format 破壊。

## ディレクトリ構成

パッケージ最上位にデータ専用 Python ファイルのみ:

```
clinosim/types/
  __init__.py           全サブモジュールの再エクスポート
  clinical.py           文書 / 所見中核型
  config.py             SimulatorConfig と実行時設定モデル
  encounter.py          Encounter と隣接運用型 (最大ファイル)
  patient.py            PatientProfile / baseline vitals / chronic conditions
  identity.py           MRN / 保険 / 国民 ID 型
  <other-domain>.py     臨床ドメインごとに 1 ファイル (上表参照)
```

## テスト

```bash
pytest tests/unit -k types -q
```

`clinosim.types` を参照するテストファイルは約 152。純粋なデータ型
なので、消費側コードを通じて間接的にテストされます。直接的な型テスト
は `__post_init__` 正規化と StrEnum wire 値に焦点。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。
