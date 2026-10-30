# `clinosim.modules.identity` — 住民識別子・保険番号付与

## 概要

[`clinosim.modules.population`](../population/README.ja.md) が生成する全
住民に対し、POST_POPULATION パスで `IdentityTimeline` (national
identity + insurance enrollment) を付与する。国別の番号生成規則は
`IdentityProvider` Protocol の背後に隠蔽され、新国追加は provider
ファイル + locale YAML の 2 点セットで完了する (engine 側の変更不要、
AD-54)。

## Scope

- **In scope**: 世帯単位の保険番号付与 (共有 記号 / member id +
  member 個別 枝番) と個人 national identity (JP マイナンバー式
  個人番号 + マイナ保険証 保有)、および card 保有に世帯内 相関を
  与える per-household 潜在変数の共有 draw。
- **有効な provider**: JP と US。US provider (Issue #1107) は
  `locale/us/identity.yaml` の `sampling.insurance_distribution` から
  member ごとに年齢帯別 `InsuranceEnrollment` を 1 件 sample する
  (65 歳以上は Medicare 系に強制、合成 11 桁 member id、記号 / 枝番
  なし)。`assign_personal` は素の `NationalIdentity(country="US")` を
  返し SSN は生成しない。従来の `insurance_type` 文字列は引き続き
  [`clinosim.modules.patient.activator`](../patient/README.ja.md) で
  別途 sample される。enricher は `enabled=lambda c:
  c.jp_insurance_numbers if is_jp(c.country) else True` のため、JP は
  `--no-jp-insurance` opt-out に従い、US は常に実行。
- **sim 途中の新生児** (Issue #1581): `assign_identity_for_person` が
  1 人分の identity timeline を付与し、`Household.identity_latent` に
  保存済みの世帯潜在変数を再利用する。新生児登録時に
  `clinosim/modules/population/person_init.py` から呼ばれる。
- **Out of scope**: 姓名 / 住所 / 生年月日 生成
  ([`clinosim.modules.population`](../population/README.ja.md) +
  [`clinosim/locale/<country>/`](../../locale/))、
  医療者 ID ([`clinosim.modules.staff`](../staff/README.ja.md))、
  FHIR serialization ([`clinosim.modules.output`](../output/README.ja.md))。

## Public API

```python
from clinosim.modules.identity import (
    assign_identities,           # (registry, country, master_seed) -> None (mutate)
    get_provider,                # (country) -> IdentityProvider (JP or US)
)
from clinosim.modules.identity.assign import (
    assign_identity_for_person,  # (registry, person, country, master_seed) -> None (mutate、新生児用)
)
```

拡張の seam となる Protocol 型は 2 つ:

- `ResidentLike` (`base.py`) — provider が必要とする構造的最小
  (`person_id`, `household_id`, `age`, `sex`, `date_of_birth`,
  `occupation`)。本モジュールが `clinosim.modules.population` を
  import しないためだけに存在する。
- `IdentityProvider` (`base.py`) — 国別番号付与契約:
  `assign_household(members, rng, config)` は
  `{person_id: InsuranceEnrollment}` map を返し、
  `assign_personal(member, household_latent, rng, config)` は
  member 個別の `NationalIdentity` を返す。

`providers/` に専用 README を置いていない — country-plugin dispatch
パターンと `IdentityProvider` 契約は上で網羅しており、per-directory
README は重複するだけになる。

## 決定論

- サブ seed オフセット `540_054` (decimal、grandfathered — identity
  seed は hex-ASCII 命名規約制定より前に確定していたため、cross-cursor
  byte-identity 保全のためそのままにしてある)。
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["identity"]` に登録済み。
- run あたり RNG 1 つ: `master_seed + ENRICHER_SEED_OFFSETS["identity"]`
  (単純加算、`derive_sub_seed` は不使用) を世帯順に消費。患者主 RNG
  列は乱さない (AD-16)。
- `assign_identity_for_person` は個人別 RNG
  (`int(sha256(f"{master_seed}|identity_person|{person_id}|v1")[:4]) +
  master_seed + ENRICHER_SEED_OFFSETS["identity"]`) を使い、batch 列を
  消費しない。
- 世帯単位で `rng.standard_normal()` を 1 回だけ draw し、
  `household_latent` (`Household.identity_latent` に保存) として全
  member に配布。JP の Gaussian-copula
  card 保有モデルはこれで marginal 年齢帯別レートを厳密に保ちつつ
  世帯内相関を生む。

## 依存

- `clinosim.modules._shared` — `is_jp`, `is_us` (canonical 国 predicate)。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`。
- `clinosim.types` — `IdentityTimeline`, `NationalIdentity`,
  `InsuranceEnrollment` (`clinosim.types` から import)。
- `clinosim.locale.loader` — `load_identity_config(country)`
  (`clinosim/locale/<country>/identity.yaml` を load)。
- `numpy` — `np.random.Generator`, `standard_normal`。
- **非依存**: `clinosim.modules.population` (`ResidentLike` で
  structural typing)。

## 定数と設定

- Registry (`registry.py`): `_SUPPORTED = {"JP", "US"}`。それ以外の国
  → `get_provider` が `ValueError`。`is_jp` / `is_us` を必ず使い、
  `country == "JP"` の直比較は FP-UNIFY-4 anti-pattern (小文字
  `"jp"` を弾いてしまう)。
- Locale YAML: [`clinosim/locale/jp/identity.yaml`](../../locale/jp/identity.yaml)
  — マイナンバー card 保有・マイナ保険証 登録の年齢帯レート、
  保険 scheme 分布、Gaussian-copula 世帯内相関の `household_icc`。
  [`clinosim/locale/us/identity.yaml`](../../locale/us/identity.yaml)
  — 年齢帯別 `sampling.insurance_distribution` + `payers`。
  `identity.yaml` を持たない国では `assign_identities` が早期 return。
- 番号生成 (`generators.py`):
  - `my_number(rng)` — 12 桁 個人番号 + 有効 check digit
    (`my_number_check_digit(base11)` で算出)。
    公式は `11 - ((Σ P_n·Q_n) mod 11)`、remainder が 0 or 1 のとき
    check digit は `0`。
  - `insurer_number(houbetsu, prefecture, serial, *, national=False)`
    — 8 桁 保険者番号 (社保 / 後期高齢者) または 6 桁 (国保)、
    末尾 mod-10 check digit を `mod10_check_digit` で付与。
  - `mod10_check_digit(body)` — modulus-10 (右から weights
    2, 1, 2, 1、積の桁を和加算)。公式仕様との突合は `# TODO: verify`
    保留。
  - `numeric_id(rng, width)` — zero-pad 済み random numeric ID。
  - `branch_number(index)` — 2 桁 枝番 (被保険者 record 内個人番号)。

## ディレクトリ構造

```
clinosim/modules/identity/
  __init__.py                     公開 API (get_provider + assign_identities)
  assign.py                       assign_identities POST_POPULATION パス + assign_identity_for_person (新生児)
  base.py                         ResidentLike + IdentityProvider Protocol
  generators.py                   my_number / mod10 / insurer_number / …
  registry.py                     国 → provider dispatch (JP / US)
  providers/
    __init__.py                   JPIdentityProvider + USIdentityProvider 再 export
    jp.py                         JP 番号規則 + card 保有 copula
    us.py                         US 年齢帯別保険 enrollment (Issue #1107)、national ID なし
```

**`enricher.py` / `audit.py` / `reference_data/` は存在しない** —
reference data は `clinosim/locale/{jp,us}/identity.yaml`、enricher entry
は `assign.py` の `assign_identities`。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) の
`register_builtin_enrichers` で登録:

- `name="identity"`, `stage=POST_POPULATION`, `order=10`,
  `enabled=lambda c: c.jp_insurance_numbers if is_jp(c.country) else True`。
- POST_POPULATION パスの序盤に実行。order 10 は `allergy` と同順で
  name 順により `allergy` が先、以降の POST_POPULATION enricher より前。
- `run` lambda は `ctx.population`, `ctx.config.country`,
  `ctx.master_seed` を渡す — enricher は stateless。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Enricher registry | [`clinosim/simulator/enrichers.py:144-152`](../../simulator/enrichers.py) | POST_POPULATION order=10 登録。 |
| `PersonRecord.identity` field | [`clinosim/types/population.py:98`](../../types/population.py) | 下流 code は本パス実行後に `person.identity.national` / `person.identity.enrollments` を読む。 |
| FHIR `Patient` / `Coverage` builder | [`clinosim/modules/output/fhir_r4/`](../output/fhir_r4/) | `Patient` にマイナンバー式 identifier、`Coverage` に保険証情報 (JP) / payer enrollment (US) を emit。 |
| 新生児登録 | [`clinosim/modules/population/person_init.py`](../population/person_init.py) | sim 途中の新生児に `assign_identity_for_person` を呼ぶ (Issue #1581)。 |

## テスト

```bash
pytest tests/unit -k identity -q         # provider + generator + assign_identities
pytest tests/e2e -k identity_jp -q       # JP locale end-to-end
```

個別ファイル:

- [`tests/unit/test_identity.py`](../../../tests/unit/test_identity.py)
  — provider dispatch、`assign_identities` の冪等性 + 決定論、
  番号生成の check digit 検証。
- [`tests/e2e/test_identity_jp.py`](../../../tests/e2e/test_identity_jp.py)
  — JP cohort end-to-end (世帯共有、card 保有率、保険者分布)。
- [`tests/unit/test_fhir_coverage.py`](../../../tests/unit/test_fhir_coverage.py)
  — enrollment からの Coverage emit。
- [`tests/unit/modules/population/test_newborn_registration_1564.py`](../../../tests/unit/modules/population/test_newborn_registration_1564.py)
  — `assign_identity_for_person` による新生児 identity。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
