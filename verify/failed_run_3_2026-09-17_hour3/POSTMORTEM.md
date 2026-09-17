# Failed Run 3 (2026-09-17, hour 3) — Postmortem

## 事実

- Boot 13:55:47 JST → shutdown 14:59:37 JST = **33 min of hour 3 billing (¥990)**
- **Case data ゼロ**
- 累計 3 hour 消費、**¥2970 sunk cost、Case data ゼロ**

## 4 attempts in hour 3

### Attempt 1 (14:27:49): Plan A (torch.compile cache 削除、CUDA_HOME 未設定)
- Failure: `flashinfer/jit/cpp_ext.py:61 get_cuda_path` → `RuntimeError: Could not find nvcc`
- Learning: cache cleanup alone insufficient、実 root cause は nvcc-less env

### Attempt 2 (14:38:41): Plan B (pip rebuild ~/vllm-env、`~/vllm-env.uv-broken.*` に旧移動)
- Rebuild successful: clinosim 0.6.2 / vllm 0.27.1 installed via pip (no uv)
- vLLM boot again failed at `flashinfer/jit/cpp_ext.py` same error
- Learning: **uv drift was NOT the root cause**、nvcc availability こそ本質

### Attempt 3 (14:46:32): Plan C1 (`--gdn-prefill-backend triton`)
- vLLM 0.27.1 の GDN prefill warning が Failed Run 1 log にあった (`Set --gdn-prefill-backend triton to skip JIT`)、追加試行
- 別の flashinfer path で crash: `flashinfer/sampling.py:68 get_sampling_module → build_and_load()` → 同じ nvcc-not-found
- Learning: flashinfer has multiple JIT paths (GDN prefill / sampling / etc.), gdn-prefill 1 flag では不十分

### Attempt 4 (14:53:42): Plan C2 (`CUDA_HOME=$HOME/vllm-env/lib/python3.12/site-packages/nvidia/cu13` export)
- **nvcc pip 内発見**: `~/vllm-env/lib/python3.12/site-packages/nvidia/cu13/bin/nvcc` 存在
- CUDA_HOME + PATH export で nvcc 発見できるように
- 進捗: weight load OK、torch.compile OK、**flashinfer 通過** (nvcc 使用でコンパイル成功)
- **新たな crash**: `vllm/utils/deep_gemm.py:453 fp8_gemm_nt` → `deepgemm-src/csrc/apis/../jit/compiler.hpp:228 "NVCC compilation failed"`
- 実 error: nvcc は動くが、CCCL header (`nvidia/cu13/include/cccl/cuda/std/__cccl/cuda_capabilities.h` 等) 経由の compilation で失敗
- Learning: **pip の nvcc 単体では insufficient**、system CUDA toolchain 完全構成 (gcc/g++ + system headers 一貫性) が必要

## Root cause 総合

**vLLM 0.27.1 は runtime JIT compile が dependency-tree の複数箇所に存在**:
- `flashinfer/jit/cpp_ext.py` — flashinfer attention/sampling kernel
- `flashinfer/sampling.py:get_sampling_module` — top-k/top-p sampler
- `vllm/utils/deep_gemm.py` — FP8 GEMM kernel via deepgemm
- `qwen_gdn_linear_attn.py` — GDN prefill (bypassable via `--gdn-prefill-backend triton`)
- 他にも RMS norm、attention 等 potential JIT sites 有

各 JIT path が nvcc + working CCCL headers を要求。pip の cuda-toolkit wheel は nvcc binary を提供するが、CCCL header の完全な toolchain には不足。

**S117 で成功した理由**: おそらく S117 時点では JIT compile が不要な pre-built binaries が dep resolution で選ばれていた、または JIT が fall-back で skip されていた。S117 → 現在の間で vllm-env が再構築される際 (uv 移行等) に、JIT-required wheel が選ばれるように挙動が変わった。

## 次 session の Plan D

**確実な fix**: system-wide CUDA toolkit install。boot 直後 H100 に:

```bash
ssh sakura 'sudo apt update && sudo apt install -y cuda-toolkit-13-0'
# 所要: 15-30 min、disk ~2-3 GB
```

CUDA 13.0 toolkit は nvcc + CCCL headers + libcuda + gcc/g++ 互換 flag 全部揃う。pip の nvidia/cu13/wheel と version 一致 (CUDA 13.x)。

**test-first approach**:
1. Boot H100
2. Install cuda-toolkit-13-0
3. `nvcc --version` で version 確認
4. **手動で vllm serve 起動して SUCCESS 確認** (verify runner 走らせる前)
5. SUCCESS なら verify run 実行
6. FAIL なら abort + shutdown、追加の env var 検討

**estimated cost for successful next-session run**:
- Boot: ~5 min
- CUDA install: ~20 min
- Manual vllm test: ~15 min (first boot cold-compile with proper toolchain)
- Verify run (11 cases): ~60 min
- Shutdown: ~1 min
- **Total ~100 min = 2 billing hours = ¥1980 additional (¥4950 grand total)**

**Time budget alternative**: 使用中の vLLM を version pin (e.g. 0.6.x or 0.7.x) で S117 相当 config に戻す
- clinosim v0.5.0 era で S117 が本当に何 vLLM version を使ったか、`~/vllm-env/lib/python3.12/site-packages/vllm-*.dist-info/METADATA` から確認可
- 実は S117 log の "version 0.27.1" は現在の再 install 後の value であり、S117 当時は違う version だった可能性

## 保存された artifact

- `run.log` — runner orchestrator log
- `master.log` — orchestrator + case output combined
- `rebuild_venv.log` — Plan B rebuild output
- `vllm_16k_S117.log` — vLLM startup log (最終 attempt 4 の deep_gemm crash 含む)
- `s117_vllm_config_recovery.txt` — Step -2 diagnostic (pip freeze 済版)

## 累積コスト

- Hour 1: ¥990 (torch.compile cache poisoning hypothesis 発見)
- Hour 2: ¥990 (uv drift hypothesis 発見、無罪判明)
- Hour 3: ¥990 (JIT compilation whack-a-mole 判明、CUDA_HOME + full toolchain 必要と確定)
- **Grand total: ¥2970、Case data ゼロ**

**投資回収**: hour 4 で Plan D (system CUDA toolkit install) を試すか、または verify を諦めて別 approach (小さい模擬モデルで prompt structure だけ検証、あるいは analysis のみで結論作成) を検討。
