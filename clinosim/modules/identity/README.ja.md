# clinosim.modules.identity — 住民識別子・保険付番 (country-pluggable)

> Status: **Phase 1 完了** (AD-54)。骨格 + JP 付番 + population 統合 + FHIR `Coverage`(JP Core 準拠)+ 個人番号 chokepoint。
> Phase 2 以降(期間付き履歴・75歳移行・就労遷移)は `TODO.md` 参照。

## 目的

住民 (Layer 1) に対し、**国別の識別子・保険資格**を付番する単一モジュール。

- **被保険者番号 (member id) / 保険者番号 (insurer number) / 記号 (group symbol) / 枝番 (branch number)** を生成
- 日本では **マイナンバーカード保有 / マイナ保険証登録**の状態 (日付付きフラグ) も保持
- 12 桁の **個人番号 (national_id)** は Layer 1 のシミュレーション属性としてのみ保持し、**臨床出力 (FHIR/CSV) には出さない** (法制度上、医療機関は個人番号を保持しない)

`disease` / `encounter` の「YAML を足すだけで追加、エンジン無改変」と同じ思想で、
**プロバイダ実装 + `locale/<cc>/identity.yaml` を足すだけで国を追加**できる。

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Country-pluggable** | `registry` が `country → IdentityProvider` を解決。新国はプロバイダ + YAML 追加のみ |
| 2 | **付番は別パス・専用サブシード** | 人口生成完了後に独立 Generator で付番し、既存乱数列・golden を壊さない (AD-16) |
| 3 | **個人番号は非出力 (privacy chokepoint)** | `national_id` は CIF に持てるが、出力アダプタは既定で機微フィールドを出さない |
| 4 | **保険資格は期間付き履歴** | enrollment は `valid_from`/`valid_to` を持ち、各受診は受診日に有効な資格を参照 (FHIR `Coverage.period`) |
| 5 | **記号の共有粒度を制度どおり** | 社保=事業所単位、国保=世帯単位、後期高齢=個人単位 |

## Dependencies

このモジュールが依存してよいもの (モジュール独立性ルール):

- `clinosim/types/` — `NationalIdentity` / `InsuranceEnrollment` / `IdentityTimeline` (types/identity.py)
- `clinosim/locale/` — `locale/<cc>/identity.yaml` (付番率・保険者代表セット・法別番号)
- `clinosim/codes/` — FHIR system URI (`get_system_uri`)

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `simulator/enrichers.py` | `--jp-insurance` 有効時に identity enricher 登録(opt-in、JP only) | optional (JP) |
| `modules/identity/assign.py` | 同 module 内 + provider 実装 | core |
| `modules/identity/registry.py` | country-pluggable provider registry | core |
| `modules/identity/providers/jp.py` | JP 保険番号 + マイナンバー生成 (provider 実装) | core |
| `modules/identity/__init__.py` | public API re-export | infrastructure |
| `modules/population/engine.py` (README cross-ref) | 人口生成後の別パスで `assign_*()` を呼び `PersonRecord` に格納 | core |
| `modules/patient/activator.py` (README cross-ref) | `PatientProfile` へ引き継ぎ、受診日で有効資格を選択 | core |
| `modules/output/` (FHIR) | `InsuranceEnrollment` から `Coverage` + 保険者 Organization を生成 | medium (FHIR Coverage builder) |
| `tests/unit/test_identity.py` | provider + assign + registry unit tests | guard |

## API リファレンス

```python
from clinosim.modules.identity import get_provider

provider = get_provider("JP")
# 世帯単位で付番 (記号共有・枝番で個人区別・被扶養者を世帯主に紐付け)
enrollments = provider.assign_household(household, rng, config)
# 個人単位の属性 (カード保有 / マイナ保険証登録フラグ等)
identity = provider.assign_personal(person, household_ctx, rng, config)
```

## データ構造

`clinosim.types.identity` を参照 (型はモジュール内に定義しない — プロジェクト規約)。

- `NationalIdentity` — `national_id` (非出力), `has_id_card`, `id_card_linked_to_insurance`
- `InsuranceEnrollment` — `insurer_number`, `member_id`, `group_symbol`, `branch_number`, `category`, `valid_from`, `valid_to`, `system_uri`
- `IdentityTimeline` — `enrollments: list[InsuranceEnrollment]`, `card_acquired_on`, `insurance_linked_on`, `national_id`

## 生成オプション

被保険者番号 (FHIR Coverage) の付与は **JP 指定時のみ**有効で、include/exclude を選べる:

```bash
# 付与あり (既定)
clinosim generate --country JP --format cif fhir -o out/
# 付与なし
clinosim generate --country JP --no-jp-insurance --format cif fhir -o out/
```

- API: `SimulatorConfig(country="JP", jp_insurance_numbers=False)`
- 非 JP (US 等) では本オプションは無視される (付番自体が走らない)
- `off` の場合、`IdentityTimeline` は生成されず Coverage も出力されない

## ロードマップ

`TODO.md` の v0.3 / AD-54 を参照 (P1〜P4)。
