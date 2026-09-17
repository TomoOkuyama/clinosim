# Next session resume prompt — S117 narrate throughput verify (2nd attempt)

## 状況 (session 終端 2026-09-17)

**Failed Run 1 完了、¥990 消費・成果ゼロ**。詳細は `verify/failed_run_1_2026-09-17_hour1/POSTMORTEM.md`。

**判明事実 (副産物)**:
- S117 実 vLLM config 復元: `enable_prefix_caching=False`, gpu-mem 0.88, max-num-seqs 32
- First-time vLLM boot は **~17-18 min** 要 (weight load 3.3 min + torch.compile 2 min + CUDA graph capture ~12 min)
- vLLM 側 `VLLM_ENGINE_READY_TIMEOUT_S=600s` が短すぎ、初回 boot 失敗

**次 session boot 前必須修正**:
1. `run_all_cases.sh` shell timeout: 300s → 1800s (start_vllm helper 内)
2. `export VLLM_ENGINE_READY_TIMEOUT_S=1800` を各 vLLM 起動前に設定
3. Fallback logging を harness に組み込み (`verify/FALLBACK_ANALYSIS.md`)
4. Fix C (vLLM guided_json) yaml variant 用意
5. Case J (Fix C isolation) を Case matrix に追加

**時間見積り (修正後)**:
- First-time vLLM boot #1: ~17 min
- Cached vLLM restarts #2-#5: ~5-8 min each
- 10 cases × 3 min = 30 min
- Total: 17 + 4×7 + 30 + 5 (buffer) = ~80 min = **billing hour 2 に若干越境** (~¥1980)

**代替案**: `--enforce-eager` で CUDA graph 無効化 → startup ~3 min に短縮。ただし Case A_S117 (S117 exact replay) は `enforce_eager=False` 必須。他 case では検討可。

## Resume 手順

```bash
cd ~/workspace/clinosim
git checkout verify/narrate-throughput
git log --oneline -8
ls verify/
cat verify/WORK.md    # 全体計画 + 各 task の状態
```

## 次 session でやること (順序)

### 1. User go の確認 (0 min)
- `[[feedback_hourly_billed_gpu_use_full_hour]]` に従い、H100 起動は user 明示 go を待つ
- 起動 = ¥990 課金開始

### 2. Session 開始チェック (5 min)
```bash
# Sakura VM 状態
usacloud server list --zone=is1a

# ローカル成果物
git status
ls verify/*.yaml verify/*.sh verify/*.py verify/*.tar.gz
```

### 3. 事前 user check 積み残し (10-15 min)

以下 3 点、boot 前に user から確認取得:

**T2 (Case A' prompt)**: `verify/v22_prompt_en.yaml`
- v19 base + v21 switch cadence + v22 Rule 3 VERBATIM merged
- EN scaffold + JA output localization (Delirium→せん妄、canonical katakana 保持)
- 現状 v20+ P1 sub-rules (SSRI/化学療法/AKI-Cr/PRN) は JA prose のまま含む
- 質問: これで case A' として妥当か

**T6 (cleanup path list)**: `verify/cleanup_paths.txt`
- 削除対象: `~/n3_cif`、`~/*_out`、`~/narrate_*`、`~/*.log`、top-level tar.gz
- 保護対象: `~/.cache/huggingface/` (Qwen weight ~54 GB)
- 質問: 削除対象に「これは残したい」ものがないか

**T8 (vLLM flags)**: `verify/vllm_start_{16k,8k}.sh`
- `--enable-prefix-caching` on (S117 で off だった疑い、明示的に on にして測定)
- `--gpu-memory-utilization 0.9` (default)
- `--max-num-seqs 256` (default)
- 質問: これで S117 の production config と同等か、他に追加すべき flag あるか

### 4. Sakura VM boot (5 min)
```bash
usacloud server boot -y --zone=is1a clinosim-bench-h100
sleep 30
usacloud server list --zone=is1a  # IP 取得
```

### 5. Verify bundle scp + extract (3 min)
```bash
cd ~/workspace/clinosim
tar --exclude='verify/out' --exclude='verify/NEXT_SESSION.md' \
    -czf /tmp/verify_bundle.tar.gz verify/
scp -i ~/.ssh/sakura_iris_ed25519 /tmp/verify_bundle.tar.gz sakura:~/
ssh sakura 'mkdir -p ~/verify && tar -xzf ~/verify_bundle.tar.gz -C ~ && ls ~/verify/'
```

### 6. clinosim を H100 に配置 (10 min if not there)
```bash
# 想定: H100 上に ~/clinosim/ が既に checkout されている
ssh sakura 'ls -la ~/clinosim/ 2>&1 | head -3 || echo NEED_CLONE'

# NEED_CLONE の場合:
ssh sakura 'git clone https://github.com/TomoOkuyama/clinosim.git && cd clinosim && git checkout v0.6.2 && pip install -e .'
# ↑ pip install が長い場合は既存 venv を再利用
```

### 7. 実測実行 (25-30 min、H100 billing 1h 内)
```bash
ssh sakura 'cd ~/clinosim && bash ~/verify/run_all_cases.sh 2>&1 | tee ~/verify/out/master.log'
```

`run_all_cases.sh` が自動で:
- Step -1: cleanup
- Step 1: vLLM 16k boot
- Cases: A / A_prime / E / A_c64 / A_c128
- Step 5: vLLM 8k restart
- Case D
- shutdown

### 8. 結果回収 (2 min)
```bash
scp -r sakura:~/verify/out ./verify/out_$(date +%Y%m%d_%H%M)
```

### 9. H100 shutdown (即座!)
```bash
usacloud server shutdown -y --zone=is1a clinosim-bench-h100
# billing 停止確認
until usacloud server read --zone=is1a clinosim-bench-h100 --output-type=json | jq -r '.InstanceStatus' | grep -q down; do sleep 5; done
```

### 10. 分析 (10-15 min)
```bash
python verify/analyze.py --out-dir ./verify/out_<timestamp>
# → factor breakdown table + analysis.json
```

### 11. Report 記述 (30 min)
- 分析結果を `docs/verify-narrate-throughput-<date>.md` に纏める
- Factor 寄与 breakdown、推奨修正、次アクション
- master に PR 出すか、branch のまま残すかは user 判断

## Pre-boot で確定した予想仮説 (updated after R1-R4 research)

**詳細は `verify/RESEARCH_FINDINGS.md`**。

Tokenizer 事前計測 + prompt 構造解析 + vLLM KV cache 理論値計算から:

- Factor A (JA vs EN prompt): +6.1% token 差のみ — 弱い
- Factor B/C (v21→v22 content): +2.5% token 差のみ — 弱い
- Factor D 元計画 (max-len 8192): **unviable** — v22 system alone = 12k > 8k、全 request 400 fail
- Factor E (concurrency): FP16 KV cache では H100 80GB の理論上限 ~22 seqs、`--concurrency 32` は既に queue-bound

**Dominant 仮説 (発見)**: **prompt 構造 + KV cache dtype**

- **Fix A**: `${document_type}` / `${target_language}` が system: block char 22 にあるため prefix cache が 11 tokens しか cache されない。user_prompt に移すと system 全体 (11,989 tokens) が cache 可能 → 24× 削減
- **Fix B**: `--kv-cache-dtype fp8` で concurrent seq capacity 2× (22 → 45 @ 13k prompt)

Case F (Fix A) と Case G (Fix A + Fix B) が本命。Case A_c64 は削除 (FP16 KV では効果なし理論確定)、Case D は revised (12288 = S117 pre-widening) に。

**revised Case matrix**:

| Case | Prompt | max-len | KV dtype | Conc | 主目的 |
|---|---|---|---|---|---|
| A | v22 JA | 16384 | FP16 | 32 | baseline (再現) |
| A' | v22 EN scaffold | 16384 | FP16 | 32 | Factor A isolation |
| E | v21 JA | 16384 | FP16 | 32 | Factor B+C isolation |
| A_c128 | v22 JA | 16384 | FP16 | 128 | 理論 ceiling 確認 |
| **F** | **v22 JA Fix A** | 16384 | FP16 | 32 | **prompt 構造 fix** |
| **G** | **v22 JA Fix A** | 16384 | **FP8** | 32 | **Fix A + Fix B compound** |
| **G_c64** | **v22 JA Fix A** | 16384 | **FP8** | 64 | **true 並列度 scaling** |
| D_revised | v22 JA | 12288 | FP16 | 32 | Factor D revised |
| **H** | **Fix A + max_tok 2500** | **12288** | FP16 | 32 | **Level-1 tuning: 16384 依存除去** |

## 最終目標 (report 執筆時の指針)

**品質・臨床整合性・ナラティブ適切さを維持/向上した上での速度短縮**を目指す。

Report は Factor breakdown だけで終わらせず、**quality-neutral な改善候補**を
priority 付きで列挙する。

### 採用可能な速度改善候補 (quality-neutral)

Factor 実測結果を見て以下を検討:

1. **vLLM 起動 flag tuning** (Factor E 実測次第)
   - `--enable-prefix-caching` の hit rate を上げる (system prompt が per-request
     で毎回 prefill されているなら、prompt template の render 順を系統的に見直し、
     可変部分を末尾に寄せる)
   - `--gpu-memory-utilization` 上げ余地確認
   - `--max-num-seqs` 拡大で真の並列度上限を確認 (concurrency sweep 結果次第)
2. **max-model-len 適正化** (Factor D 実測次第)
   - S117 で 16384 に拡大した理由 (12289-token prompt+response overflow) は
     legitimate。しかし p=100 実測で observed prompt+response 分布を採り、
     P99+margin で足りるサイズに絞る (16384 が過剰なら 12000 等)
   - max-model-len 縮小 = KV cache 予約減 = max-num-seqs 増 = 実効並列度増
3. **Prompt 構造 (semantic 保持で token 減)**
   - description block は既に yaml comment (LLM 送信されない) なので影響なし
   - system: block 内の v22 Rule 3 拡張 (700-1000 chars) を、文言短縮で semantic
     を保ったまま ~200 chars 削減可能かレビュー
   - Rule 5 の JA translation table (Severity / Disposition / Oxygen 等) は
     使用頻度が低い entry を per-doc-type の contextual insertion に降格可能か

### 採用不可能な速度改善案 (quality regression)

- Rule 3 削除 → S117 で fix された G20/E11/M17/F32 hallucination 再発
- JA localization rule 削除 → 日本語文書適切さ regression
- v21 (Rule 3 未搭載) への恒久 revert → 同上

### Report 構造の推奨骨子

`docs/verify-narrate-throughput-<date>.md` の section:

1. Executive summary — 実測 doc/s と主要 factor
2. 測定条件 (cohort seed、prompt versions、vLLM flags、H100 config)
3. Factor breakdown table (analyze.py 出力)
4. Prefix cache hit rate analysis (vLLM /v1/metrics より)
5. GPU util analysis (nvidia-smi より、SM 占有率が bottleneck かどうか)
6. **推奨修正** priority 順 (quality-neutral のみ)
7. 各修正の expected throughput gain
8. Next steps / defer 項目

Case A' の結果は Factor A の isolation として cite するが、恒久採用候補として
は書かない (`[[feedback_llm_prompt_matches_output_language]]` を明示引用)。

## 成果物一覧 (verify/ ディレクトリ)

| ファイル | 用途 |
|---|---|
| `WORK.md` | 全体計画・Factor 表・Case matrix・進捗 |
| `NEXT_SESSION.md` | このファイル、次 session resume 手順 |
| `v22_prompt_ja.yaml` | Case A baseline (v0.6.2 現行) |
| `v22_prompt_en.yaml` | Case A' (v19 base + v21/v22 merged) |
| `v21_prompt_ja.yaml` | Case E (v22 直前) |
| `v22_prompt_en_original.yaml` | reference (現行 US EN prompt) |
| `tokens_precount.json` | Qwen tokenizer 事前計測結果 |
| `tokenize_prompts.py` | tokenizer 実行 script |
| `cohort_p100_jp_s917.tar.gz` | 本測定 cohort (546K) |
| `cohort_warmup_jp_p10_s918.tar.gz` | warmup cohort (23K) |
| `cleanup_paths.txt` | H100 Step -1 削除 path list |
| `run_case.sh` | 1 case 実行 script (H100 側) |
| `run_all_cases.sh` | 全 case orchestrator (H100 側) |
| `llm_service_vllm.yaml` | narrate 用 vLLM config |
| `vllm_start_16k.sh` | vLLM boot script (max-len 16384) |
| `vllm_start_8k.sh` | vLLM boot script (max-len 8192) |
| `sakura_ops.md` | Sakura VM 運用 command 参照 |
| `analyze.py` | post-run 分析 harness |

## Checkpoint commit 履歴

- `d83058d48b` (ckpt 1): 環境準備 + T1 + T13
- `a3691deb0c` (ckpt 2): T2 + T3
- `7e807c1559` (ckpt 3): T7 + T5 + T6
- `9c4d9ec0ba` (ckpt 3b): tar.gz force-add
- `477c279120` (ckpt 4): T4 + T8
- (ckpt 5 to be pushed): T11 + T14 + NEXT_SESSION

## What NOT to do 次 session

- **H100 boot は user 明示 go を待つ** (時間課金 ¥990/h)
- **`gh pr merge --auto` 使わない** (branch protection なし repo は CI status check を待たない、`[[feedback_auto_merge_needs_explicit_ci_wait]]`)
- **branch を master に merge しない** (investigation branch、成果 report のみ docs/ に PR)
- **cohort tarball を regenerate しない** (現行 s=917 で pre-boot 事前計測済、regenerate すると RNG cascade で prompt token 分布が変わり事前解析が invalid 化)
- **v0.6.2 tag 再 cut しない** (次 tag は v0.6.3 or v0.7.0、narrate speed fix 適用後)

## 参照 memory

- `[[feedback_hourly_billed_gpu_use_full_hour]]` — H100 1h 単位課金
- `[[feedback_llm_prompt_matches_output_language]]` — JA→JA 恒久ルール (Case A' は診断目的の temp variant)
- `[[feedback_pr_merge_autonomous_on_ci_pass]]` — CI 通ったら自動 merge (この branch は merge しない、report 側の PR に適用)
- `[[reference_ec2_access]]` — Sakura H100 access
