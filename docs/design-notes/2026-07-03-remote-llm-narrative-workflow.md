# リモート LLM narrative 実行手順書(β-JP-1 chain 1b T5)

**Date:** 2026-07-03(session 32)
**前提 chain:** 1a(context wiring、PR #136)+ 1b(LLM golden / semantic check /
`--patient-filter`、本 chain)
**運用前提(spec §0):** ナラティブの実 LLM 生成は**別サーバ**で実行する。ローカルは
MockProvider 検証のみ。本書はそのリモートサーバ上での end-to-end 手順。

## 0. 全体像

```
[リモート LLM サーバ]
  1. 環境準備(clinosim install + Ollama model pull / AWS IAM)
  2. structural CIF を用意(その場で生成 or ローカルから転送)
  3. clinosim narrate --provider ollama|bedrock [--patient-filter ...]
  4. clinosim check-narratives(semantic gate、byte-diff の代替)
  5. 合格 → narrate --set-current → clinosim export-fhir
  6. LLM golden 更新 → regenerate-goldens --provider ... --model-tag ...
     → 生成された *.llm-<tag>.golden.json をリポジトリに commit
```

byte-diff regression は deterministic generator(template / mock)専用。
実 LLM 出力の合否判定は **`check-narratives`(5 軸 semantic check)** が gate:
構造(stub↔file 1:1・section keys・空 section・fallback 比率)/ facts_used 由来 /
禁止 pattern(AI メタ応答・`[Mock`・未解決 `{placeholder}`・seed 指示文漏洩・
US 出力の日本語混入)/ per-profile 期待 phrase / 数値整合。

## 1. 環境準備

### 共通

```bash
git clone <repo> && cd clinosim
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[llm]"        # httpx (ollama provider) を含む
pytest -m unit -q              # サーバ上で環境健全性を確認
```

### Ollama の場合

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gpt-oss:20b        # session 32 smoke で実績のあるモデル
ollama serve &                 # デフォルト http://localhost:11434
```

設定は `clinosim/config/llm_service.yaml`(デフォルトが Ollama)。モデル名を
変える場合は YAML を編集するか `--llm-config` で別ファイルを渡す。

### Bedrock の場合

- EC2 に IAM role(`bedrock:InvokeModel`)を付与(EC2 メモ: memory
  `reference_ec2_access` 参照)。
- 設定は `clinosim/config/llm_service.bedrock.yaml`(Claude Sonnet 4)。

## 2. structural CIF の用意

どちらでも良い(structural CIF は seed 決定的なので、リモートで再生成しても
ローカルと byte 一致する):

```bash
# (a) その場で生成 — profile 単位(golden 用)
clinosim test-disease --patient-profile tests/fixtures/patient_profiles/jp_inpatient_bacterial_pneumonia.yaml \
    --format cif -o /tmp/pneumonia

# (b) その場で生成 — cohort 単位(品質確認用)
clinosim generate -p 100 --country JP --format cif -o /tmp/jp100

# (c) ローカルから転送
rsync -az ./output/cif/ remote:/data/run1/cif/
```

## 3. narrate(実 LLM 生成)

```bash
clinosim narrate --cif-dir /tmp/jp100/cif \
    --provider ollama \
    --country JP \
    --version-id "gpt-oss-20b-$(date +%Y%m%d)" \
    --no-set-current
```

要点:

- `--version-id` は**モデル + 日付**で命名(narrative version は並存可能;
  `narratives/<version_id>/` に書かれ、`current_version.txt` は動かない)。
- LLM provider のデフォルトは `--no-set-current`(M-3)— trial run が
  production export を silent に差し替えることはない。
- provider 不通時は template fallback で完走し、**全滅時は stderr WARNING**
  (I-2)+ manifest `llm_cost_report.generator_fallback_docs` に記録される。
  check-narratives の structure 軸も fallback > 0 を FAIL にする。

### 反復チューニング loop(`--patient-filter`)

prompt や モデル設定を触りながら 1 患者だけ何度も回す:

```bash
clinosim narrate --cif-dir /tmp/jp100/cif --provider ollama --country JP \
    --version-id trial-7 --patient-filter "ENC-POP-000002"   # filename stem or patient_id の regex
```

- filter は patient JSON の **filename stem と patient_id の両方**に対する
  regex(`ENC-A|POP-000777` のような alternation 可)。
- 部分実行 version は manifest に `patient_filter` が記録され自己記述的。
- **golden を filter 付きで作ることは不可能**(`regenerate-goldens` は
  `--patient-filter` を exit 2 で拒否 — 部分 golden 事故防止)。

## 4. check-narratives(semantic gate)

```bash
# profile 実行の場合(期待 phrase 込み)
clinosim check-narratives --cif-dir /tmp/pneumonia/cif \
    --version "gpt-oss-20b-20260703" \
    --profile jp_inpatient_bacterial_pneumonia \
    --report /tmp/report.json
echo $?   # 0 = PASS / 1 = findings / 2 = expectations 不備

# cohort 実行の場合(builtin 軸のみ)
clinosim check-narratives --cif-dir /tmp/jp100/cif --version "gpt-oss-20b-20260703"
```

- expectations は `tests/fixtures/patient_profiles/<name>.llm-expectations.yaml`
  (`--expectations PATH` で差し替え可)。
- findings は stdout に軸別で列挙、`--report` で JSON 全文。CI 組込みは
  exit code をそのまま使う。

## 5. 合格後: set-current + FHIR export

```bash
clinosim narrate --cif-dir /tmp/jp100/cif --provider ollama --country JP \
    --version-id "gpt-oss-20b-20260703" --set-current
# (再生成せず pointer だけ動かしたい場合は narratives/current_version.txt を直接編集でも可)

clinosim export-fhir --cif-dir /tmp/jp100/cif --country JP \
    --narrative-version "gpt-oss-20b-20260703"
```

## 6. LLM golden の更新(profile 単位)

```bash
clinosim regenerate-goldens --all --provider ollama --model-tag gpt-oss-20b
# → tests/fixtures/patient_profiles/<name>.llm-gpt-oss-20b.golden.json × 6
```

- `--model-tag` は golden ファイル名の tag(省略時は provider 名)。実モデルの
  tag を必ず明示すること(モデル更新時に別 golden として並存できる)。
- 実 LLM golden は **byte-diff 用ではない**(非再現)— レビュー・比較・
  ドリフト検知の参照物。regression suite の byte-diff leg は
  `<name>.llm-mock.golden.json`(deterministic)にのみ適用される。
- 生成後: `git add tests/fixtures/patient_profiles/*.llm-gpt-oss-20b.golden.json`
  → ローカルへ持ち帰り PR に含める(AD-66 Rule 1 と同じ「golden は必ず
  commit とセット」原則)。

## 7. コスト・所要時間の目安

LLM が実際に書き直すのは `stage2_strategy: template_seed` の 2 doc type ×
各 2 section のみ(admission_hp: hpi + assessment_and_plan / discharge_summary:
hospital_course + discharge_instructions)。他 7 doc type は template のまま。

| 単位 | docs 総数 | LLM 呼出し(section 単位) | 備考 |
|---|---|---|---|
| 6 profiles golden 一式 | ~158 docs | 6×(2 docs×2 sections)= **24 calls** | 各 call max 800 output tokens |
| p=100 JP cohort(参考) | 入院患者数に比例 | 入院 1 人あたり 4 calls | NarrativeCache が同一臨床 bucket + 同一 seed の患者間で呼出しを削減 |

- Ollama(ローカル GPU): API 費ゼロ。gpt-oss:20b で 1 call 数秒 →
  golden 一式は数分オーダー。
- Bedrock(Claude Sonnet 4): 24 calls × (input ~1k tokens + output ~800
  tokens)/ call 程度 — golden 一式で数十円オーダー。`PromptCache`(disk)が
  同一 prompt の再実行を dedupe、walk order が (doc_type, language) group
  serial なので Bedrock prompt cache(5 分 TTL)にも hit しやすい(AD-65)。
- 実測は manifest `llm_cost_report`(total_calls / input_tokens /
  output_tokens / generator_fallback_docs)で確認する。

## 8. トラブルシューティング

| 症状 | 見る場所 | 対処 |
|---|---|---|
| 全 doc が template のまま | stderr WARNING + manifest `generator_fallback_docs` | provider 起動 / `--llm-config` の model 名を確認 |
| check-narratives が `[Mock` で FAIL | manifest `generator` | 実 provider のつもりが mock 構成になっている(llm-mock 以外の version で `[Mock` は常に FAIL) |
| 未解決 `{placeholder}` finding | 該当 section | seed(template)側の問題 — encounter YAML の placeholder が未知。chain 1b T4 の vitals 対応外なら TODO 化 |
| 期待 phrase FAIL | `<name>.llm-expectations.yaml` | 臨床的に正しい言い換えなら expectations 側を緩める(any_of へ)。事実が消えているなら prompt contract 違反 → モデル/プロンプト調整 |
