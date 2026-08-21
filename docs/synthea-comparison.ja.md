# `clinosim eval` で clinosim と Synthea を比較する

[Synthea](https://synthetichealth.github.io/synthea/) (MITRE の
state-transition 合成健康記録ジェネレータ) と clinosim は同じ問題に
異なる角度から取り組みます。このページは設計上の相違
([Feature comparison](#feature-comparison) / [When to use which](#when-to-use-which))
から始まり、両ツールを **同一** 評価軸で採点して定量的な side-by-side
比較を行う方法を示します。clinosim は Synthea の patient 別 Bundle
出力を `clinosim eval` が期待する ResourceType 別 NDJSON レイアウトに
展開するアダプタを同梱。

!!! note "Synthea はオプション依存"
    clinosim のランタイムには Synthea を import / 依存する箇所は一切
    ありません。Java (11+) は Synthea コホート生成時のみ必要です。
    出力がディスク上に存在すれば、以降は Python のみで動作します。

## Feature comparison

| 次元 | clinosim | Synthea |
|---|---|---|
| モデル化アプローチ | 生理駆動の前向きシミュレーション (患者ごとに 14 変数の hidden state) | 疾患別 state-transition モジュール |
| 検査 / vital 間の整合性 | 共有生理状態により保証 | モジュールごとに独立 |
| ネイティブ FHIR R4 出力 | Bulk Data Access NDJSON、ResourceType ごとに 1 ファイル | patient ごとに FHIR R4 JSON |
| JP Core プロファイル準拠 | 16 resource type | 設計目標ではない |
| 多 locale (US + JP) | 両方が first-class; JP 氏名 / 住所 / 保険 / JLAC10 / MHLW YJ | US ファースト; 国際化はコミュニティモジュール経由 |
| 決定性保証 | 同一 seed に対し MINOR リリース内でバイト同一出力 | 実行 seed ごとに決定的 |
| 拡張モデル | YAML 駆動 (ファイル編集、コード不要) | Java モジュール (`.json` state machine + コード) |
| ランタイム | Python 3.11+ | Java 11+ |
| ライセンス | MIT | Apache 2.0 |

## When to use which

- **clinosim** — 臨床整合的な検査 / vital、JP 出力、または Java
  コードを触らずに疾患定義を反復したい場合。
- **Synthea** — 確立された疾患モジュールと成熟した下流ツール
  エコシステムを持つ広範な US 集団が必要な場合。

## 1 — Synthea コホートを生成

Synthea は Java ベース。実行の簡単な 2 通り:

### Docker

```bash
mkdir -p ./synthea-out
docker run --rm \
    -v "$(pwd)/synthea-out:/output" \
    docker.io/mitre/synthea:latest \
    -p 100 \
    --exporter.fhir.export=true \
    --exporter.fhir.transaction_bundle=true \
    --exporter.baseDirectory=/output \
    California San_Francisco
```

FHIR R4 出力は `./synthea-out/fhir/` に着地 — patient ごとに 1 JSON
ファイル (トップレベル FHIR Bundle の `entry[].resource` リストが
Patient / Encounter / Observation / … を保持)。

### Java 直接

素の `.jar` ルートを好むなら:

```bash
git clone https://github.com/synthetichealth/synthea.git
cd synthea
./run_synthea -p 100 \
    --exporter.fhir.export=true \
    California San_Francisco
# → output/fhir/<uuid>.json
```

population サイズ / 州 / config オプションは
[Synthea wiki](https://github.com/synthetichealth/synthea/wiki)
参照。

## 2 — `clinosim eval` で Synthea コホートを採点

`clinosim eval` を Synthea の `fhir/` 出力に向けるだけ — レイアウト
は自動検出され、Bundle ファイルは併置される
`fhir_r4/<ResourceType>.ndjson` に正規化されます:

```bash
clinosim eval -d ./synthea-out/fhir
# clinosim eval: detected Synthea layout — normalizing into ./synthea-out/synthea-normalized
# clinosim eval: wrote 12345 resources across 18 ResourceType(s)
# ...
# Overall score: 82.4 / 100 (WARN)
```

正規化は決定的 (同じ Bundle → 同じ NDJSON バイト); 同一入力に対する
以降の `eval` 実行は on-disk `synthea-normalized/` を再利用 (削除
しない限り)。

`--synthea-normalize` で targetディレクトリを強制指定:

```bash
clinosim eval -d ./synthea-out/fhir \
    --synthea-normalize /tmp/synthea-flat \
    --json synthea-eval.json \
    --md synthea-eval.md
```

## 3 — 等価な clinosim コホートを採点

比較可能な clinosim コホートを生成 — `us-100` プリセットは同等の
サイズ / 国 / 期間の球場:

```bash
clinosim dataset build us-100 --output ./clinosim-out
clinosim eval -d ./clinosim-out \
    --json clinosim-eval.json \
    --md clinosim-eval.md
```

## 4 — 軸ごとに比較

関心のある軸で 2 つの JSON レポートを diff:

```bash
python3 - <<'PY'
import json
a = json.load(open("synthea-eval.json"))
b = json.load(open("clinosim-eval.json"))
print(f"{'axis':<15} {'synthea':>10} {'clinosim':>10}")
for ax_a, ax_b in zip(a["axes"], b["axes"]):
    assert ax_a["axis"] == ax_b["axis"]
    print(f"{ax_a['axis']:<15} {ax_a['score']:>10.1f} {ax_b['score']:>10.1f}")
print(f"{'overall':<15} {a['overall_score']:>10.1f} {b['overall_score']:>10.1f}")
PY
```

出力例 (実際の比較は異なる):

```
axis            synthea    clinosim
structural         98.5      100.0
clinical           74.2       77.8
locale             85.0      100.0
overall            85.9       92.6
```

スコアリング式は [Evaluation](eval.ja.md#スコアリング)、check ごとの
合格基準は [Evaluation rules](eval-rules.ja.md) 参照。

## 両ツールが正当に異なる採点になる箇所

- **Structural.** 両ツールとも valid な FHIR R4 を emit するので、
  ここのスコアは近くなるはず。structural ギャップは主にリソース
  cardinality: 例えば Synthea は Encounter ごとに `CareTeam` を emit
  しないが、clinosim は session 46 P0 以降 emit する。
- **Clinical.** clinosim の生理学モデルは
  [eval-rules.ja.md](eval-rules.ja.md) の `condition_lab_coherence`
  ペアリングでチューニングされているので、clinosim コホートは
  構造上ほぼ高スコアになるはず。Synthea の state-transition モジュール
  は prevalence と進行でチューニングされていて別品質軸。coherence
  check は Synthea の疾患別検査モジュールと eval band が合致しない
  ペアリングを浮上させる。どちらの結果も本質的に「間違い」ではない
  — 何を測っているかの問題。
- **Locale.** clinosim の JP check
  (`japanese_displays_on_condition` / `jlac10_or_loinc_on_lab` /
  `yj_code_on_medications` / `jp_core_profile_declared`) は Synthea
  出力に対して fail する — Synthea は US ファーストなので。eval
  ツールは Synthea がこれらの閾値を狙って作られていないことを指摘
  しているのであり、Synthea が壊れているわけではない。Synthea を
  採点するときは `--country US` で locale 軸を US check に制限する。

## 両方に公平なルールを追加する

比較を公開する予定なら、
[eval-rules.ja.md](eval-rules.ja.md) の "ルール追加" が check
セットの単一編集点。ここに追加した新規ルールは次の eval 実行で両
ツールを一貫して採点します。

## 関連

- [Evaluation](eval.ja.md) — CLI + スコアリングリファレンス。
- [Evaluation rules](eval-rules.ja.md) — check ごとの合格基準 + 文献。
- [Datasets](reference/datasets.md) — clinosim プリセットコホート。
- [Reproducibility](development/reproducibility.md) — clinosim の
  バイト同一決定性契約。
- [Synthea ドキュメント](https://github.com/synthetichealth/synthea/wiki)。
