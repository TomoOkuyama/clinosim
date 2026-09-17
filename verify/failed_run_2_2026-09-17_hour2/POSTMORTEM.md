# Failed Run 2 (2026-09-17, hour 2) — Postmortem

## 事実

- Boot 13:55 JST → shutdown 14:18 JST = **23 min の hour 2 billing (¥990)**
- **Case data 取得: ゼロ** (Case A_S117 の vLLM startup が engine core init で crash)
- 総費用: Failed Run 1 (¥990) + Failed Run 2 (¥990) = **¥1980、成果ゼロ**

## Root cause: `torch.compile` cache poisoning

vLLM boot #0 (S117 config replay) は次のエラーで失敗:
```
RuntimeError: Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist
```
(engine core initialization、~6 min into boot、14:03:31 UTC)

### なぜ S117 で起こらず今回起こったか

| フェーズ | torch_compile_cache 状態 | 挙動 |
|---|---|---|
| **S117 (Sept 15)** | 空 (fresh) | source から compile、cache-cold path (nvcc 不要)、成功 |
| **Failed Run 1 (今 hour 1)** | S117 の cache は VM 再起動 or vLLM 更新で invalidated → fresh compile 中 | 内部 600s vLLM timeout で crash、**cache 2.1GB を partial write** |
| **Boot 2 (今 hour 2)** | Failed Run 1 の partial/inconsistent cache 存在 | cache validity check で nvcc invoke → **nvcc 未 install → 失敗** |

Failed Run 1 が「crash 直前まで書き込んだ cache」を Boot 2 が読もうとしたのが引き金。cache-cold は nvcc 不要、cache-hit-validation は nvcc 必要という vLLM 0.27.1 の設計に、partial cache が半端に触れて失敗パスに入った。

### 証拠

- vLLM engine core error at 14:03:31: `RuntimeError: Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist`
- Failed Run 1 の `/home/ubuntu/.cache/vllm/torch_compile_cache` は 2.1GB で存続
- vllm-env は Aug 中盤時期に構築済 (nvcc は元から未 install、CUDA runtime + drivers のみ)

## Learnings for next boot

### 必須 pre-boot 修正

`run_all_cases.sh` の Step -1 (cleanup) に torch_compile_cache 削除を追加:

```bash
# 破損 cache による cache-hit-validation の nvcc invocation を防ぐ。
# vLLM は cache-cold なら nvcc 不要 (S117 で実証済)、cache-hit-partial だと
# nvcc 必要になり失敗する (Failed Run 2 で実証済)。安全側で削除。
rm -rf ~/.cache/vllm/torch_compile_cache ~/.cache/vllm/torch_aot_compile
echo "torch.compile caches cleared to force fresh cold-compile path"
```

**トレードオフ**: cache 削除で毎 boot が cold-compile になり ~2 min 追加。しかし cache 破損リスクを完全に排除できる (~¥990 節約 vs ¥33 の余分 billing)。

### 代替対策

1. **`nvidia-cuda-toolkit` を H100 に install** (30 min + ~1GB disk): nvcc invoke でも問題なくなる。恒久解決。
2. **`--enforce-eager` を全 vLLM boot に**: torch.compile 全 skip、CUDA graph も無効化 (5-10% inference 遅延)、cache 依存ゼロ
3. **vLLM 環境変数**: `VLLM_USE_V1=0` で V0 engine 使用 (compile 少ない)、あるいは torch.compile disable

### 各 fix の trade-off

| 対策 | Pros | Cons |
|---|---|---|
| torch.compile cache 事前削除 | 最短 (1 行)、S117 replay 忠実 | boot 毎に ~2 min 余分 (cache cold rebuild) |
| CUDA toolkit install | 恒久解決 | 30 min + disk 1GB、環境変更 |
| `--enforce-eager` 全 boot | 確実に nvcc 不要、boot 短縮 (5 min) | S117 exact replay 崩れ、inference 5-10% 遅延 |

**推奨**: 最短 (Option 1) + `--enforce-eager` fallback を用意。Boot 3 の Step -1 に cache 削除、成功したら S117 replay 有効。もし cache 削除でも同じ nvcc error が出るなら `--enforce-eager` fallback に切替。

## 状態

- H100: shutdown 完了 (14:18 JST)、billing 停止済
- torch_compile_cache: **H100 上に残存**、次 boot 時に削除必要
- verify branch: checkpoint 14 (`ca3ee9fa8e`) — Boot 2 の変更なし (Failed Run 2 log は VM に置き去り)
- 次 session に必要な追加 fix: `run_all_cases.sh` の Step -1 に cache 削除追加、`--enforce-eager` fallback yaml 用意

## 累積コスト

- Hour 1 (Failed Run 1): ¥990、result ゼロ、副産物: S117 config 復元 + first-boot timeline
- Hour 2 (Failed Run 2): ¥990、result ゼロ、副産物: torch.compile cache 破損 hypothesis 判明
- **合計 ¥1980、Case data ゼロ**

次 boot は Step -1 に cache 削除 fix を組み込んで再挑戦。
