# H100 環境調査 — なぜ S117 で動いた vLLM が今回動かないか

**目的**: S117 (2026-09-15) は vLLM 0.27.1 + Qwen3.8-27B-FP8 で成功、Failed
Run 1-3 (2026-09-17) は同 vLLM version + 同 config でも engine core
init crash。差分を特定して次 boot 前に fix する。

**方針**: **step-by-step で command 出力を確認しながら**、仮説を消去法で
絞る。H100 boot ごとに料金が発生するので、確実性の高い調査項目のみを
実行する。

## 判明済 事実

### S117 (成功時) vs 現在 (失敗時)

| 項目 | S117 (2026-09-15) | 現在 (Failed Run 1-3) |
|---|---|---|
| vLLM version banner | `version 0.27.1` (H100 log 実測、`vllm_p100_v5.log`) | 同 `version 0.27.1` |
| Model | Qwen/Qwen3.8-27B-FP8 | 同 |
| Startup flags | max-model-len 16384、gpu-mem 0.88、max-num-seqs 32、PC OFF | 同 |
| **エラー** | **なし (narrate 完走)** | **flashinfer/deep_gemm JIT nvcc compilation fail** |

### Failed Run 1 vLLM log の重要 line (2026-09-17 12:39:26)

```
INFO gpu_model_runner.py:5308 Starting to load model Qwen/Qwen3.8-27B-FP8...
WARNING import_utils.py:408 Module vllm.third_party.deep_gemm was found but failed to import
   ... _find_cuda_home() ... assert cuda_home is not None ... AssertionError
INFO __init__.py:634 Selected CutlassFp8BlockScaledMMKernel for Fp8LinearMethod
INFO qwen_gdn_linear_attn.py:150 Using FlashInfer GDN prefill kernel (requested=auto, head_k_dim=128).
```

**Point**:
1. deep_gemm import failed (CUDA_HOME 未設定のため) → **fallback**
   `CutlassFp8BlockScaledMMKernel` に silent 切替
2. FlashInfer GDN prefill kernel が selected → JIT compile 必要 → 後で
   crash

S117 も同じく CUDA_HOME 未設定だったはず (Sakura VM default)。であれば
S117 も deep_gemm import 失敗 → Cutlass fallback、FlashInfer GDN で JIT
compile。**S117 では JIT compile が成功していた** — 理由は?

## 仮説

### H1: S117 は persistent JIT cache がホームに残っていた

vLLM の JIT-compiled kernel は多くの場合 `~/.cache/flashinfer/`、
`~/.cache/vllm/torch_compile_cache/` 等の永続 cache に保存される。S117
の直前に成功した boot がこれらを populated しており、S117 boot は cache
hit で JIT compile を skip した可能性。今 session の Failed Run 1 boot
時には (or S117 → 今 session の間の VM restart で) cache が消失、cold
JIT compile が要求されて nvcc-not-found で crash。

**検証コマンド (H100 内でチェック)**:
```bash
ls ~/.cache/flashinfer/ 2>&1 | head -5
ls ~/.cache/vllm/torch_compile_cache 2>&1 | head -5
find ~/vllm-env -path "*/flashinfer*" -name "*.so" 2>/dev/null | head -5
find ~/vllm-env -path "*/deep_gemm*" -name "*.so" 2>/dev/null | head -5
# → pre-compiled .so があるか?
```

### H2: pip-installed cu13 wheel が S117 時と現在で異なる build

同じ `vllm==0.27.1` でも、pip resolver / uv resolver がタイミングで異なる
build hash の wheel を取得している可能性。特に nvidia-* 依存の cu13
wheels は各 minor version で SDK compatibility が微妙に変わる。

**検証コマンド (H100 boot 直後、rebuild 前に)**:
```bash
source ~/vllm-env/bin/activate && pip freeze | grep -E "^(vllm|torch|flashinfer|nvidia|xformers|deep-gemm|xgrammar)" | sort
```

これを S117 時代の同 command 出力と比較 → **私たちは S117 時代の出力を
保存できていない** (VM state に依存)。ただし failed_run_1 の
`s117_vllm_config_recovery.txt` に一部 pip freeze が残っている。

### H3: /usr/local/cuda を過去に system-install していたが upgrade / uninstall で消失

Ubuntu 24.04 の nvidia-cuda-toolkit を過去 install → S117 時に `nvcc` が
system path で使えた → その後 apt upgrade or 手動 uninstall で消失、
Failed Run 1 時には CUDA_HOME 未設定 & /usr/local/cuda 不在。

**検証コマンド**:
```bash
dpkg -l | grep -E "cuda|nvcc|nvidia-cuda" | head -10
apt list --installed 2>/dev/null | grep -Ei "cuda|nvcc"
# apt history log
grep -aE "cuda|nvcc" /var/log/apt/history.log* 2>/dev/null | head -30
```

### H4: vLLM 内部の kernel compile cache が S117 boot の副産物として残存、これが今回消えた

vLLM は torch.compile の AOT compile artifact を
`~/.cache/vllm/torch_compile_cache/`、CUDA graph capture の PTX cache を
別 dir に、それぞれ保存する。S117 の最初 boot 時に compile cache がなく
JIT compile が要求されたが、その時は nvcc あった (system install) →
success + cache populated → 以降の boot は cache hit で success。今 は
system nvcc なし → cold-compile で fail。

**H3 と H4 は複合仮説**: cuda-toolkit を過去 apt install した状態で S117
初回 boot、その後 apt upgrade or manual removal で toolkit 消失、cache
は残る、cache-hit で S117 継続 boot 動作、subsequent VM restart で cache
も消失、今回 fresh cold-compile 状態で fail。

### H5: pip の cu13 wheel が nvcc を含むが、CCCL header と互換性のない
system gcc/g++ を要求

Failed Run 3 attempt 4 で判明: CUDA_HOME を pip の cu13 に向けても、
`deep_gemm` の JIT compile が `NVCC compilation failed` (CCCL header
経由の C++)。system default `gcc` / `g++` version が cu13 wheel の nvcc
と非互換。S117 時代の apt install cuda-toolkit なら matching gcc/g++ が
同時に入り互換性有。

**検証コマンド (H100 内)**:
```bash
gcc --version; g++ --version
which nvcc; nvcc --version 2>&1 | head -5
find /usr /opt -name "cccl*" -type d 2>/dev/null | head -5
```

## 調査 execution plan (H100 boot 1 回、~30 min、¥990)

**Boot 目的**: 上記 H1-H5 を確認 (verify なしで shutdown)。verify runner
は起動しない。

**Step-by-step commands** (SSH 1 sessions で連続実行):

```bash
# 0. Boot & connect
usacloud server boot -y --zone=is1a clinosim-bench-h100
sleep 30
ssh -i ~/.ssh/sakura_iris_ed25519 ubuntu@133.242.22.166

# 1. H1 (JIT cache remnants)
ls -la ~/.cache/flashinfer/ 2>&1 | head -5
ls -la ~/.cache/vllm/ 2>&1 | head
ls -la ~/.cache/deep_gemm/ 2>&1 | head -5
find ~/.cache -name "*.so" -newer /etc/hostname 2>/dev/null | head -10
find ~/vllm-env -name "*.so" -path "*flashinfer*" | head -3
find ~/vllm-env -name "*.so" -path "*deep_gemm*" | head -3

# 2. H2 (pip freeze)
source ~/vllm-env/bin/activate
pip freeze | grep -E "^(vllm|torch|flashinfer|nvidia|xformers|deep-gemm|xgrammar|triton)" | sort

# 3. H3 (system CUDA install history)
dpkg -l 2>&1 | grep -iE "cuda|nvcc" | head -10
apt list --installed 2>/dev/null | grep -Ei "cuda|nvcc" | head -10
ls /var/log/apt/history.log* 2>/dev/null
grep -aE "cuda|nvcc" /var/log/apt/history.log* 2>/dev/null | head -30

# 4. H5 (compiler compat)
gcc --version; g++ --version
which nvcc
find / -maxdepth 5 -name "nvcc" 2>/dev/null | head -5
find /usr /opt -type d -name "cccl*" 2>/dev/null | head -5
find /usr -name "cuda_runtime.h" 2>/dev/null | head -3

# 5. Emergency fix candidate: install cuda-toolkit apt
sudo apt list --upgradable 2>/dev/null | grep -i cuda
apt-cache search cuda-toolkit 2>/dev/null | head -10

# 6. shutdown
exit
usacloud server shutdown -y --zone=is1a clinosim-bench-h100
```

**判定ロジック**:

- H1 で cache/.so files あり → cache 消えた仮説を裏付け、cache 復元 (or
  clean cold-compile が nvcc 完備で走れば OK)
- H2 で pip freeze の diff が s117 時代と大差 → wheel drift、pin して
  再 install
- H3 で apt history に過去 cuda install がある → 再 install で復元、
  S117 状態に戻す
- H5 で gcc/g++ が cu13 nvcc 非互換 → matching gcc/g++ install が必要

## Fix plan (H1-H5 の判定結果次第)

### Case A: H3 で「過去 cuda-toolkit apt install log」があれば
```bash
sudo apt update
sudo apt install -y nvidia-cuda-toolkit  # matching gcc/g++ も同時に入る
which nvcc  # /usr/bin/nvcc appears
sudo ln -s /usr/lib/nvidia-cuda-toolkit /usr/local/cuda  # optional
```
これで CUDA_HOME=/usr、nvcc + CCCL + matching gcc/g++ 一式揃う。S117
状態に近づく。

### Case B: H1 で cache が残っていれば
何もせずに再 boot、cache-hit で JIT compile 回避されるか確認。

### Case C: H2 で pip drift 疑い
```bash
pip install --force-reinstall --no-deps 'vllm==0.27.1' 'flashinfer-python==<S117 version>'
```
S117 時代の flashinfer / vllm pin を復元 (要 pip freeze from S117 log)。

## 次 session action items

1. H100 boot (¥990 hour 4) → 上記 step-by-step 診断のみ (~20-30 min)、
   verify runner 起動しない
2. 診断結果を verify/H100_ENV_DIAGNOSIS_<date>.md に記録
3. 判明した root cause に応じて Fix (Case A / B / C) を pre-apply
4. 別 boot (¥990 hour 5) で run_all_cases.sh 実行、11 case 完走
5. Total 追加 cost 見積り: ~¥1980 (grand total ¥4950)

**もし診断だけで hour 4 使い切れば**: hour 4 の 40+ min 残時間で
run_all_cases.sh を fire、Fix が効いていれば 3-4 case 走れる。効かなければ
即 shutdown、hour 5 に持ち越し。

## 現段階での省略可否

- H100 boot なしで結論を出す case: pre-boot analysis + report
  (`docs/verify-narrate-throughput-2026-09-17.md`) を merge 対象とし、
  Fix C (`--enable-prefix-caching`) を最優先で production の vllm serve
  command に追加する PR を出す。実測なしで ship する risk あり (品質
  regression 起きうる) が、pre-boot 理論分析からは有力。

user 判断: **診断投資 (¥1980) vs 実測なし ship (0 円だが不確実)**。
