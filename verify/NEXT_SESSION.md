# Next session resume prompt — S117 narrate throughput verify

## 状況 (session 終端 2026-09-17)

**Pre-boot 準備完了**、次 session は **H100 boot + 実測 + 分析** から開始。

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

## Pre-boot で確定した予想仮説

Tokenizer 事前計測から:
- Factor A (JA vs EN prompt): +6.1% token 差のみ
- Factor B/C (v21→v22 content): +2.5% token 差のみ
- → **50% throughput 低下は Factor D (max-len) or Factor E (vLLM flag/prefix cache) が dominant**

Case D と prefix cache hit rate が最重要指標。Case A' の operational value は「品質保った EN 化で速さ戻るか」の decision-relevant answer として二次的。

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
