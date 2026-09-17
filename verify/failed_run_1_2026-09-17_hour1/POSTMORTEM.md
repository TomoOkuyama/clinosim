# Failed Run 1 (2026-09-17, hour 1) — Postmortem

## 事実

- Boot 12:33 JST → Shutdown 13:17 JST = **44 min の hour 1 billing (¥990)**
- **Case data 取得: ゼロ** (Case A_S117 の vLLM startup 中に timeout error)
- root cause: `VLLM_ENGINE_READY_TIMEOUT_S=600s` を超過 (first-time boot は ~17 min 必要)

## 判明した事実 (副産物として)

### S117 実運用 vLLM 起動 config (from `~/vllm_p100_v5.log` + `~/vllm_jp_p10k.log`)

```
{model: Qwen/Qwen3.8-27B-FP8, host: 127.0.0.1,
 max_model_len: 16384,
 gpu_memory_utilization: 0.88,
 max_num_seqs: 32,
 enable_prefix_caching: False,
 kv_cache_dtype: auto (FP16),
 dtype: bfloat16, quantization: fp8,
 enable_chunked_prefill: True (default)}
```

**Critical**: S117 は `enable_prefix_caching: False` で走っていた。これが Factor E の根本原因。

### First-time vLLM boot timeline (from `vllm_16k_S117.log`)

- 12:38:39: APIServer start
- 12:39:06: EngineCore start
- 12:39:26 → 12:42:46: **Weight loading = 3.3 min** (28.51 GiB, 199s)
- 12:42:46 → 12:44:56: **torch.compile = 2 min** (125s, cache miss on first boot)
- 12:44:56 → 12:49:06 (timeout hit): **CUDA graph capture in progress** (未完了、~12 min 必要と推定)

合計 first-boot 時間: ~17-18 min (vs. cached rerun: 5-8 min 想定)

## Learnings for next session

### 必須修正

1. `run_all_cases.sh` の shell wait timeout: 300s → **1800s (30 min)**
2. Environment: `export VLLM_ENGINE_READY_TIMEOUT_S=1800` を各 vLLM 起動前に設定
3. First-boot 用の warmup step を明示 (最初の vLLM boot は ~17 min かかる旨、runbook に記載)

### 費用対策

- **cache 温めスクリプト**: verify run の 前 step として、cheap な vLLM boot を 1 回実行して torch.compile cache + CUDA graph をキャッシュ (billing 数分だが後続の 4 boots が高速化)
- **`--enforce-eager` オプションの検証**: CUDA graph 無効化で startup 高速化 (5-10% 遅くなるが startup が ~3 min に)
  - Case A_S117 (S117 replay) では `enforce_eager=False` (CUDA graph on) 必須で、trade-off 不可
  - 他 case では検討価値あり
- **fewer vLLM restarts**: 4 restart 前提を見直し。同じ vLLM で異なる config は本質的に不可能なので必要だが、まとめ順序 (A_S117 → A_pc → A' → E → A_pc_c128 → F → G → G_c64 → D_revised → H → shutdown) を最適化

### Fallback 0 目標の統合

user が mid-verify に提起 (`verify/FALLBACK_ANALYSIS.md` 参照):
- 全 case で fallback rate を metric として計測
- Fix C: vLLM `guided_json` で JSON 出力を文法制約
- Case J: Fix C 単独検証追加

### 保存された artifact

- `run.log` — runner log (1.7K)
- `vllm_16k_S117.log` — vLLM startup log (48K、timeline evidence)
- `s117_vllm_config_recovery.txt` — Step -2 output (S117 config recovery source)

## 次 session boot 前 checklist

1. `run_all_cases.sh` shell timeout 修正 (300 → 1800s)
2. `VLLM_ENGINE_READY_TIMEOUT_S=1800` を各 start_vllm 呼び出し前に export
3. Fallback logging を harness に組み込み (`FALLBACK_ANALYSIS.md` §追跡)
4. Fix C (guided_json) yaml variant 用意
5. Case J (Fix C isolation) を Case matrix に追加

見積り: 実施すれば hour 1 で 10 case + 5 vLLM restarts + shutdown が完走可能 (~50 min)。
