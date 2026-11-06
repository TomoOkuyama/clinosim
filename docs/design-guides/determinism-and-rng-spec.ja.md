# 決定性と乱数 — 仕様

位置づけ: **規範**。乱数を引く・シードを導く・時計を読む・シミュレーション内で動く処理を足す変更は、すべて本書に従う。従えない変更は、同じ PR で理由とともに本書を改訂する。

英語版: [`determinism-and-rng-spec.md`](determinism-and-rng-spec.md)。背景とクロスプラットフォームの経緯: [`docs/development/reproducibility.md`](../development/reproducibility.md)。[`implementation-rules.ja.md`](implementation-rules.ja.md) §3 の要約は本書を指す。

## 1. 原則

1. **同じ入力なら同じ出力。** 実行は設定(人口・シード・日付・国・プロバイダ)だけの純関数で、出力は実行・マシン・CPU アーキテクチャをまたいでバイト一致する(AD-16)。
2. **乱数生成器の生成元は一つ。** 乱数生成器はすべて `clinosim.determinism.default_rng` で作る。それ以外で numpy の生成器を作らず、Python の `random` モジュールや大域乱数状態も使わない。
3. **シード導出は一つ。** シードはすべて `clinosim/seeding.py`(登録済みのモジュールオフセットか名前付きシード関数)から得る。Python の `hash()`・時計・オブジェクト id・集合の反復順からは作らない。
4. **局所ストリーム。** 各判断は、その判断の対象(患者・入院・オーダー・日)をキーにしたストリームから引く。ある判断を変えても別の判断の乱数はずれない(AD-59)。
5. **生成経路で時計を読まない。** シミュレーション上の時刻は設定と生成済みの事象から決まる。実時間は実行メタデータにだけ使う(§5)。
6. **規則には必ずガードがある。** 以下の各規則は、それを強制するテストを示す。テストのない規則は §8 に挙げる。

## 2. 乱数を引く

| 規則 | 正準コード | ガード |
|---|---|---|
| 生成器は `determinism.default_rng(seed)` だけで作る。numpy PCG64 のプロキシで、`normal` / `standard_normal` / `beta` / `exponential` をビット再現なアルゴリズム(固定精度の `mpmath`)で引き、それ以外(`random`, `integers`, `choice` …)は整数演算がどこでも同一な numpy に委ねる。 | `clinosim/determinism.py`(`default_rng`, `normal`, `beta`, `exponential`) | `tests/unit/test_rng_through_determinism_2529.py`(`determinism.py` 以外に `np.random.default_rng` が無い)、`tests/unit/test_determinism.py` |
| 生成経路で Python の `random` モジュールを import しない。 | — | `tests/unit/test_determinism_spec_guards.py::test_no_stdlib_random` |
| YAML 由来の確率ベクトルは `rng.choice(p=...)` の前に `normalize_probabilities(p, fallback="raise")` を通す。 | `clinosim/modules/_shared.py::normalize_probabilities` | `implementation-rules.ja.md` §4(レビュー) |
| ストリームを要さない選択(看護師・左右・時刻などの安定した「ランダム風」の選択)は生成器でなくハッシュを使う。乱数を消費しないので、足してもストリームはずれない。 | `determinism.sha_quantile` / `sha_bernoulli` / `sha_weighted_choice`、`seeding.rendezvous_pick` / `id_hashes`、`seeding.morse_fall_history_unit` | `tests/unit/test_seeding.py` |

## 3. シードを導く

| 規則 | 正準コード | ガード |
|---|---|---|
| モジュールのストリームは `derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS[<モジュール>], <対象キー>)`。オフセットはモジュール名の 16 進 ASCII(4 バイト)で一度だけ登録し、モジュール間で重複しない。`identity` と `microbiology` は既存の 10 進値を維持する。 | `seeding.derive_sub_seed`, `seeding.ENRICHER_SEED_OFFSETS` | `tests/unit/test_enricher_seed_offsets.py`, `tests/unit/test_seeding.py` |
| シミュレーションフェーズのストリームは `derive_phase_rng(master_seed, PHASE_<名>, key)`。フェーズの salt は `_PHASE_OFFSETS` に登録する。 | `seeding.derive_phase_rng`, `PHASE_LIFE_EVENT` / `PHASE_INPATIENT_SIM` / `PHASE_READMISSION` / `PHASE_OUTPATIENT_CAL` / `PHASE_ED_VISIT` | `tests/unit/test_seeding.py` |
| 繰り返し使う対象ごとのストリームには名前付きシード関数があり、呼び出し側はみな同じ導き方をする。 | `seeding.py`: `panel_specimen_seed`(検査パネル)、`individual_lab_seed`(検査オーダー)、`chronic_medication_seed`, `discharge_prescription_seed`, `ambulatory_visit_length_seed`, `issue939_procedure_seed`, `chronic_augment_sex_seed`, `chronic_isolated_seed`, `longitudinal_event_seed`, `perinatal_delivery_seed`, `chemotherapy_regimen_seed`, `daily_output_seed`, `text_seed` | `tests/unit/test_seeding.py`(検査シードは式を固定) |
| シードは `hashlib.sha256` で計算し、`hash()`(`PYTHONHASHSEED` でプロセスごとに変わる)は使わない。 | `seeding.derive_sub_seed`, `seeding.text_seed` | `tests/unit/test_determinism_spec_guards.py::test_no_builtin_hash_call` |

## 4. 変更で乱数をずらさない

新しい機能・項目・モジュール・修正は、変えないものの乱数を動かしてはならない。優先順:

1. **乱数を引かない。** 生成済みのデータかハッシュ(§2 最終行)から値を導く。例: 左右のある画像検査の側(`imaging_laterality`)、配置オーダーの投与看護師(`placed_order_mar.stable_nurse`)、Morse 転倒歴項目。
2. **新しい局所ストリームから引く。** 対象をキーにサブシードを作る(`derive_sub_seed(seed, offset, f"{encounter_id}:{specimen}:{n}")`)。新モジュールなら新しいオフセットを登録する。
3. **既存ストリームに引きを挿入しない。** 引きの順序を入れ替えない。新しいデータで引くかどうかを分岐させない。いずれもそのストリームの以降の引きをすべてずらし、背後にキャッシュされた患者(人物キャッシュの F4 メモ化)もずらす。

結果を変えざるを得ない変更(モデル変更)は、どのストリームが動いたかと、コホートへの効果(§6)を PR に書く。

## 5. 時計

| 規則 | 正準コード | ガード |
|---|---|---|
| 生成は実時間を読まない。シミュレーション時刻は `--start` / `--end` と事象から決まる。必須時刻のデータクラス既定値は番兵 `_UNSET_DATETIME`(1970-01-01)で、`datetime.now()` ではない。 | `clinosim/types/clinical.py`, `clinosim/types/encounter.py`(`_UNSET_DATETIME`) | `tests/unit/test_wallclock_sentinel_defaults.py`, `tests/unit/test_fhir_bundle_no_wallclock.py` |
| 実時間は実行メタデータにだけ使う: Bulk Data マニフェストの `transactionTime`、`_generator_metadata.json`、CIF メタデータの `generation_timestamp`、ナラティブ版の `generated_at`、CLI の既定値(`--end` の既定は当日)、レポート。これらはバイト差分の対象外。 | ガードで許可したファイル | `tests/unit/test_determinism_spec_guards.py::test_wall_clock_only_in_run_metadata` |

## 6. 検証

- `bash scripts/reproduce.sh` は実行を再現し、全出力ファイルの sha256 を比べる。
- 出力不変のはずの変更は、同じ基点コミットから作った master に対して CIF・FHIR のバイト差分 0 を示す(US と JP)。
- 結果を変える変更は、同じ基点コミットのコホートを比べ、変わったパス(例 `orders[].result`, `microbiology`)と差分のある患者数を PR に書く。意図しないストリームのずれが見えるようにするため。

## 7. 反復順とキャッシュ

- 引きにつながる集合・辞書の走査は先に並べ替える。並べ替えない集合の順序は文字列ハッシュに依存する。
- `@lru_cache` ローダーの戻り値は共有物で、書き換えない(`implementation-rules.ja.md` §3)。
- enricher の順序(`stage` + `order`)と `NarrativePass` の走査順は固定。変えるとストリーム変更になる(§4)。

## 8. 未対応

既知のものは無い。新たな例外は、ガードの許可リストへの追加とともにここに記す。
