# narrate throughput regression investigation

## 目的

**測定対象**: **pure LLM 生成速度** (CIF 生成時間・narrate setup overhead 除外)。
測定は server-side `/v1/metrics` (vLLM Prometheus) を authoritative source とし、
`vllm:generation_tokens_total` / `vllm:e2e_request_latency_seconds` の
delta を pure-LLM metric として採る。narrate CLI の wall-clock は L2 として
補助的に、CIF I/O + prompt build + output save を含むので絶対値評価には使わない。

**最終目標**: **データ品質 + 臨床的整合性 + ナラティブ文書としての適切さを**
**維持/向上した上で** LLM 生成時間を短縮する。

**品質制約 (quality guardrails)**:
- v22 Rule 3 (ICD VERBATIM COPY on chronic conditions) は保持必須 — S117 で
  実測された 3 US docs G20→"glaucoma" hallucination の fix。削除は臨床整合性の
  regression になる。
- v19 の JP output localization (Delirium→せん妄、canonical katakana、Kanji
  section heading) は保持必須 — ナラティブ文書としての日本語文書適切さの basis。
- v22 の per-doc-type block (admission_hp / discharge_summary / operative_note /
  ...) 構造は保持必須 — 各文書種の "記述すべき情報の定義" を encode。

**採用可能な速度改善候補** (quality-neutral):
- vLLM 起動 flag tuning (prefix caching、gpu-mem-util、max-num-seqs)
- `--max-model-len` 適正化 (16384 が必要かの実測、8192 で足りるならそちらへ)
- Prompt 構造 (system prompt を prefix cache 対象として最大化する render 順)
- Rule 記述の compression (semantic 同一、token 減少)
- concurrency sweep で真の並列度上限を確認

**採用不可能な改善案** (quality regression):
- Rule 3 削除 (品質 regression)
- JA localization rule 削除 (文書適切さ regression)
- v21 に戻す (Rule 3 未搭載で hallucination 再発)
- Prompt 言語を EN に恒久変更 (JA 出力品質不安定化)

Case A' は「診断用の temp variant」であり、恒久採用候補ではない — Factor A
の影響量を測るための tool。

## 原因切り分けの sub-question

v22 prompt cut (S117 = v0.6.2) を境に narrate throughput が 1.35 → 0.68 doc/s
(~2×) に低下した原因を切り分ける。

## 仮説 (寄与因子)

| ID | Factor | 変化内容 | 主 metric | S117 slowdown 帰属 |
|---|---|---|---|---|
| A | prompt 言語 | JA prompt (system block 日本語) | input token 数 | **v20 (S114) で導入** — S117 slowdown の帰属外の可能性大 |
| B | prompt 内容 | v21 → v22 に Rule 3 (VERBATIM) 追加 (system: block +14 lines) | input token 数 | 直接 S117 帰属 |
| C | output 内容 | Rule 3 で ICD-10-CM full label emit (chronic 5 疾患 ≒ ~25 extra chars/doc) | completion token 数 | 直接 S117 帰属 |
| D | context 上限 | `--max-model-len 8192 → 16384` (S117 で拡大) | KV cache 予約、concurrency slot | 直接 S117 帰属 |
| E | vLLM 起動 flag | prefix-caching / gpu-mem / max-num-seqs | throughput 全般 | 環境固有 |

**重要な事前観察 (T3 tokenizer 実測から確定)**:

| Case | version | tokens | 対 v22 JA 差 |
|---|---|---|---|
| v22 JA (現行) | 22 | **11,966** | — |
| v22 EN Case A' | 22 | 11,239 | **-727 (-6.1%)** |
| v21 JA (Case E) | 21 | 11,669 | **-297 (-2.5%)** |

- **Factor A (JA vs EN system prompt)**: 727 tokens = **6.1%** の差
- **Factor B/C (v21→v22 content 追加)**: 297 tokens = **2.5%** の差
- 単純に prompt token 数の変化だけでは 50% throughput 低下 (1.35→0.68 doc/s) を説明不能。線形近似なら +6.1% は速度 -6% 程度に留まる
- → **Factor D (max-len 16384) と Factor E (vLLM 起動 flag / prefix caching hit rate) が dominant 仮説**
- H100 検証優先度: **Case D + vLLM flag 確認 > Case A' (EN prompt)**。ただし Case A' は「品質保った上で EN framing に戻すと速さが戻るか」の operational answer として残す価値あり

## Case 一覧 (revised per R1-R4 findings; see RESEARCH_FINDINGS.md)

| Case | prompt | max-len | KV dtype | conc | 目的 |
|---|---|---|---|---|---|
| A | v22 JA | 16384 | FP16 | 32 | baseline (現行) |
| A' | v22 EN scaffold | 16384 | FP16 | 32 | Factor A isolation |
| E | v21 JA | 16384 | FP16 | 32 | Factor B+C 合算 |
| A_c128 | v22 JA | 16384 | FP16 | 128 | Factor E — ceiling check (theory: no gain) |
| **F** | **v22 JA Fix A** | 16384 | FP16 | 32 | **prompt 構造 fix (prefix cache 復活)** |
| **G** | **v22 JA Fix A** | 16384 | **FP8** | 32 | **Fix A + Fix B compound** |
| **G_c64** | **v22 JA Fix A** | 16384 | **FP8** | 64 | **true concurrency scaling** |
| D_revised | v22 JA | **12288** | FP16 | 32 | Factor D (max-len 効果、8k は unviable と判明) |
| **H** | **Fix A + max_tokens=2500** | **12288** | FP16 | 32 | **Level-1 tuning: max_tokens 緊縮で 16384 依存除去** |
| **J** | **v22 JA + guided_json** | 16384 | FP16 | 32 | **Fix C: user goal fallback 0 (structured output)** |

**Dropped**:
- Case A_c64 — FP16 KV では ~22 seq ceiling で頭打ち理論確定、A_c32 と差なし予想
- Case D at 8192 — system alone = 12k tokens で 8k 全 request fail 確定 (R1)

## metric 3 層

- **L1** (pure inference): `Δgeneration_tokens / Δtime` server metric。startup / warmup / transport 除外
- **L2** (end-to-end pure narrate): client-side per-doc timestamp。warmup 除外
- **L3** (wall-clock): `N / total_wall`。参考のみ

## Pre-boot deliverables 状況

| # | task | 成果物 | status |
|---|---|---|---|
| — | 環境準備 (branch + verify/ + WORK.md) | — | ✅ done |
| T1 | v22 JA prompt freeze | `verify/v22_prompt_ja.yaml` (933 lines, from fa024893f2) | ✅ done |
| T13 | v21 prompt 復元 | `verify/v21_prompt_ja.yaml` (904 lines, from 4115f563a8) | ✅ done |
| T2 | v22 EN 翻訳 (user check) | `verify/v22_prompt_en.yaml` (937 lines, v19 base + v21/v22 merged, Case A') | ✅ done |
| — | tokenize script (T3 支援) | `verify/tokenize_prompts.py` | ✅ done |
| T3 | tokenizer 事前計測 | `verify/tokens_precount.json` (Qwen3-8B tokenizer) | ✅ done |
| T7 | 本 cohort CIF (p=100 JP s=917) | `verify/cohort_p100_jp_s917.tar.gz` (546K) | ✅ done |
| T5 | warmup cohort (p=10 JP s=918) | `verify/cohort_warmup_jp_p10_s918.tar.gz` (23K) | ✅ done |
| T6 | 削除 path list (user check) | `verify/cleanup_paths.txt` | ✅ done |
| T4 | narrate client harness | `verify/run_case.sh` + `verify/run_all_cases.sh` + `verify/llm_service_vllm.yaml` | ✅ done |
| T8 | vLLM 起動 script 2 種 (user check) | `verify/vllm_start_{16k,8k}.sh` | ✅ done (user review 待ち) |

## 次 session に持ち越し

3h 内で当初 defer 予定だった T9/T10/T11/T14/T16/T17 も追加で仕上げた。残りは:

| # | task | 想定所要 | 状態 |
|---|---|---|---|
| T9 | weight cache 保護 | — | ✅ cleanup_paths.txt に統合 |
| T10 | metric 収集 script | — | ✅ run_case.sh に統合 (inline curl + nvidia-smi dmon) |
| T11 | post-hoc 分析 harness | — | ✅ done (`verify/analyze.py`) |
| T12 | S117 0.68 doc/s メタデータ復元 | 10 min | ⏳ next session |
| T14 | Sakura VM 運用 command 確認 | — | ✅ done (`verify/sakura_ops.md`) |
| T15 | 予算プリチェック (user 承認) | 1 min | ⏳ next session (user go 前) |
| T16 | 時計同期プラン | — | ✅ sakura_ops.md に統合 |
| T17 | Case 実行順序 runbook 化 | — | ✅ run_all_cases.sh に統合 |
| T18 | verify report 骨子 | 10 min | ⏳ post-run に post-run で書く |
| — | **H100 boot 実行** | **1h billing (¥990)** | ⏳ next session、user go 待ち |
| — | post-run 分析 + report | 1h | ⏳ next session |

**Resume 手順は `verify/NEXT_SESSION.md` 参照**。

## Checkpoint commit 履歴

| # | timestamp | scope | SHA |
|---|---|---|---|
| 1 | 2026-09-17 | 環境準備 + T1 + T13 (v22 + v21 prompt freeze) | d83058d48b |
| 2 | 2026-09-17 | T2 + T3 (Case A' prompt + tokenizer precount) | a3691deb0c |
| 3 | 2026-09-17 | T7 + T5 + T6 (cohorts + cleanup list) | 7e807c1559 / 9c4d9ec0ba (tarball force-add) |
| 4 | 2026-09-17 | T4 + T8 (harness + vLLM scripts) | 477c279120 |
| 5 | 2026-09-17 | T11 + T14 + NEXT_SESSION (analyze + Sakura ops + resume prompt) | 0945c207fa |
| 6 | 2026-09-17 | goal 明確化 (pure LLM 速度 + quality-preserving) | 188658a92f |
| 7 | 2026-09-17 | analyze.py bugfix + S117 baseline meta + report template | 01fe425b64 |
| 8 | 2026-09-17 | R1-R4 pre-boot research + Case matrix revision (Fix A/B pre-built) | (pending) |

## Session 切断時の resume 手順

1. `cd ~/workspace/clinosim && git checkout verify/narrate-throughput`
2. `git log --oneline` で最終 checkpoint 確認
3. この WORK.md の「Pre-boot deliverables 状況」table で残 task を確認
4. TaskList でも同 task を復元済 (memory 側)

## 参照 memory

- `[[feedback_hourly_billed_gpu_use_full_hour]]` — H100 は 1h 単位、boot 毎に消費
- `[[feedback_llm_prompt_matches_output_language]]` — 恒久的 EN 化は禁止、Case A' は診断目的の temp variant のみ
- `[[feedback_pr_merge_autonomous_on_ci_pass]]` — この branch は experimental、merge しない
- `[[reference_ec2_access]]` — Sakura H100 access, ~/.ssh/sakura_iris_ed25519
