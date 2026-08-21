# `clinosim.types` — 依存グラフ最下層の共有 dataclass 群

## 目的

`clinosim.types` は他の全パッケージが import する純粋なデータ形状層で
す。患者・エンカウンター・オーダー・結果・診断・手技・アレルギー・画像
・文書・シミュレータ設定に用いる `@dataclass` / `StrEnum` /
`TypedDict` / `Protocol` を定義します。臨床ドメイン別にファイル分割
(AD-18) することで個々のファイルを可読に保ち、cross-module import を
自明化します: `from clinosim.types.encounter import Encounter` は巨大
なトップレベルモジュールより読みやすい。

本パッケージは `__post_init__` の正規化以外に **実行時ロジックを持たな
い**。型のフィールドを変更するコードは所有 module (`simulator/` /
`modules/*/` / `output/`) に属し、ここには置きません。

## スコープ

- **In scope**: 臨床・運用・identity・設定ドメインのための
  dataclass / StrEnum / TypedDict / Protocol 定義、デフォルト値・型
  強制のための最小限の `__post_init__` 正規化。
- **Out of scope**: 単純な正規化を超えてフィールドを読み書き・変更する
  コード。ビジネスロジックは `simulator/` と `modules/*/` に属し、
  YAML 読み込み・コード検索・シリアライズは各所有パッケージに属します。

## 公開 API

慣用的な import 2 形式:

```python
from clinosim.types.encounter import Encounter
# または:
from clinosim.types import Encounter          # 便宜的な再エクスポート
```

`__init__.py` の便宜的再エクスポートは **選抜されたサブモジュールの
みを対象** とし、それ以外はサブモジュールパスで import する必要があり
ます:

| サブモジュール | 内容 | トップレベル再エクスポート? |
|---|---|---|
| `clinical.py` | 臨床イベント中核型 (文書・所見) | ✅ |
| `config.py` | `SimulatorConfig` と関連する実行時設定モデル | ✅ |
| `encounter.py` | `Encounter` / `EncounterType` / `EncounterStatus` / order / 薬剤投与 | ✅ |
| `identity.py` | `PatientProfile` 識別子、JP マイナンバー / 保険型 | ✅ |
| `microbiology.py` | 培養 / 感受性型 | ✅ |
| `output.py` | コホートレベル出力メタデータ | ✅ |
| `patient.py` | `PatientProfile` / `BaselineVitals` / 慢性疾患型 | ✅ |
| `population.py` | 集団生成中間型 | ✅ |
| `procedure.py` | 手術・治療手技型 | ✅ |
| `staff.py` | スタッフ・医療者型 | ✅ |
| `allergy.py` | `Allergy` / `AllergyReaction` | ❌ 直接 import |
| `device.py` | 医療機器型 | ❌ 直接 import |
| `diagnosis.py` | 診断イベント型 | ❌ 直接 import |
| `document.py` | 文書・ナラティブ型 | ❌ 直接 import |
| `family_history.py` | 家族歴型 | ❌ 直接 import |
| `hai.py` | 医療関連感染型 | ❌ 直接 import |
| `imaging.py` | 画像検査・レポート型 | ❌ 直接 import |
| `triage.py` | ED トリアージ型 | ❌ 直接 import |

「非再エクスポート」集合は意図的です — これらのドメインは狭い呼出集合
(imaging 出力、triage 判定、diagnosis 履歴ビルダー) にのみ消費され、
明示的な import パスを強制することで依存を import 位置で可視化します。

## 決定性

該当なし — 本パッケージは import 時にも dataclass 構築時にも乱数生成
・壁時計参照・ファイルシステム I/O・環境変数参照を一切行いません。
`_UNSET_DATETIME` / `_UNSET_DATE` sentinel は固定リテラル
(`1970-01-01`) なので、同一入力は常に同一 dataclass インスタンスを生
成します。

## 依存

- 標準ライブラリ: `dataclasses` / `enum` / `datetime` / `typing`。
- `typing_extensions` (旧 Python 版向けバックポート import 用)。
- **他の `clinosim.*` モジュールへの依存なし**。types は依存グラフの
  最下層 — ここから `clinosim.simulator` や `clinosim.modules.*` を
  import すると循環となり review-blocker。

## 定数と設定

- **`_UNSET_DATETIME = datetime(1970, 1, 1)` と
  `_UNSET_DATE = date(1970, 1, 1)`** — `clinical.py` (ブロックレベル
  コメント日付 2026-07-04) で定義し `encounter.py` / `procedure.py` /
  `diagnosis.py` で再宣言。これらの sentinel は private (先頭アンダー
  スコア) で、`None` だと下流のシリアライズを壊す optional field の
  デフォルトにのみ使用。1970-01-01 epoch を意図的に選ぶことで下流の
  シリアライザが確実にフィルタ可能。
- **StrEnum wire 値** — 例えば `EncounterType.INPATIENT = "inpatient"`
  は CIF / FHIR / CSV 出力に serialize される文字列。StrEnum 値の変更
  は wire-format 破壊であり、全出力アダプタと全 consumer の CIF
  fixture を横断的に更新する必要があります。
- YAML 設定は持ちません。本パッケージは自身では設定ファイルを読まず、
  consumer 側で構築した `SimulatorConfig` インスタンスを受け取るのみ。

## ディレクトリ構成

```
clinosim/types/
  __init__.py           上表 10 サブモジュールを再エクスポート
  clinical.py           臨床イベント・文書・所見 (238 行)
  config.py             SimulatorConfig と実行時設定モデル (254 行)
  encounter.py          Encounter と隣接運用型 (311 行)
  document.py           文書・ナラティブ型 (343 行 — 最大ファイル)
  patient.py            PatientProfile / baseline vitals / chronic conditions (211 行)
  output.py             コホートレベル出力メタデータ (132 行)
  population.py         集団生成中間型 (111 行)
  procedure.py          手術・治療手技 (84 行)
  imaging.py            画像検査・レポート (75 行)
  identity.py, microbiology.py, staff.py, allergy.py, device.py,
  diagnosis.py, family_history.py, hai.py, triage.py
                        臨床ドメインごとに 1 ファイル (上表参照)
```

## テスト

```bash
pytest tests/unit -k types -q
```

`clinosim.types` を import するテストファイルは約 155。純粋なデータ型
なので、消費側コードを通じて間接的にテストされます。直接的な型テスト
は `__post_init__` 正規化と StrEnum wire 値に焦点。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
