# narrate throughput regression investigation

## 目的

v22 prompt cut (S117 = v0.6.2) を境に narrate throughput が 1.35 → 0.68 doc/s (~2×) に低下した原因を切り分ける。

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

## Case 一覧

| Case | prompt | max-len | concurrency | 目的 |
|---|---|---|---|---|
| A | v22 JA | 16384 | 32 | baseline (現行) |
| A' | v22 EN | 16384 | 32 | Factor A isolation |
| E | v21 JA | 16384 | 32 | Factor B+C 合算 |
| A/c64 | v22 JA | 16384 | 64 | Factor E (concurrency) |
| A/c128 | v22 JA | 16384 | 128 | Factor E (concurrency) |
| D | v22 JA 圧縮 | 8192 | 32 | Factor D |

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
| T7 | 本 cohort CIF (p=100) | `verify/cohort_p100.tar.gz` | pending |
| T5 | warmup cohort (p=10) | `verify/cohort_warmup.tar.gz` | pending |
| T6 | 削除 path list (user check) | `verify/cleanup_paths.txt` | pending |
| T4 | narrate client harness | `verify/run_case.sh` | pending |
| T8 | vLLM 起動 script 2 種 (user check) | `verify/vllm_start_{16k,8k}.sh` | pending |

## 次 session に持ち越し (今 3h に含まれない)

| # | task | 想定所要 |
|---|---|---|
| T9 | weight cache 保護 command | 2 min |
| T10 | metric 収集 script (scrape/dmon/measure) | 30 min |
| T11 | post-hoc 分析 harness + dry-run | 30-45 min |
| T12 | S117 0.68 doc/s メタデータ復元 | 10 min |
| T14 | Sakura VM 運用 command 確認 | 5 min |
| T15 | 予算プリチェック (user 承認) | 1 min |
| T16 | 時計同期プラン | 2 min |
| T17 | Case 実行順序 runbook 化 | 15 min |
| T18 | verify report 骨子 | 10 min |
| — | **H100 boot 実行** | **1h billing** |
| — | post-run 分析 + report | 1h |

## Checkpoint commit 履歴

| # | timestamp | scope | SHA |
|---|---|---|---|
| 1 | 2026-09-17 | 環境準備 + T1 + T13 (v22 + v21 prompt freeze) | d83058d48b |
| 2 | 2026-09-17 | T2 + T3 (Case A' prompt + tokenizer precount) | (pending) |

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
