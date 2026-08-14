# Sakura Cloud GPU + Ollama で clinosim narrate を自己ホスト

**Date**: 2026-08-15
**Status**: Design approved、実施は別セッションで実測 (VM boot 要)
**Related**: `docs/bedrock_setup.md` (AWS Bedrock ルート)、`clinosim/config/llm_service.{bedrock,cloud}.yaml`
**Motivation**: AWS Bedrock 依存を排し、国内クラウド (さくらのクラウド) 上の GPU インスタンスで日本語医療 narrative を生成できるようにする。データ主権要件や閉域運用 (医療情報 3 省 2 ガイドライン) との相性が良い。

## 目的とスコープ

**目的**: さくらのクラウド「高火力 VRT」上に Ollama を常駐させ、clinosim narrate から Ollama native + OpenAI 互換の両方 API で叩ける環境を作る。品質評価で日本語医療 narrative に適したモデルを確定する。

**スコープ**:
- 単一 GPU インスタンス (L40S 48GB) 上の Ollama サーバ構築
- Qwen 3 系モデル (32B dense) をプライマリ、その他 (Llama 3.3 70B / Swallow 70B / Qwen 3 30B-A3B MoE) を比較候補
- clinosim narrate から SSH tunnel 経由の HTTP 接続
- `clinosim/config/llm_service.sakura.yaml` の追加

**Out of scope**:
- IRIS for Health との連携 (別プロジェクト `proj-iris-sakura-verification` の Phase 3 で扱う)
- さくらの AI Engine (マネージド) との比較 (同上)
- Bedrock API 互換の変換レイヤ (LiteLLM 等) — Ollama 標準の OpenAI 互換で十分
- モデルの fine-tuning (base model を Ollama pull するのみ)
- 本番向け 24/7 常時稼働の運用設計 (研究/検証用途のオンデマンド運用を前提)

## 前提整理 (clarify 済み)

| 論点 | 決定 | 根拠 |
|---|---|---|
| Scope | clinosim narrate 専用 (sakura-iris Phase 3 と分離) | user 判断 |
| API interface | Ollama native (`/api/generate`, `/api/chat`) + OpenAI 互換 (`/v1/chat/completions`) の両方 | Ollama 0.1.14+ で標準機能、LiteLLM 追加コスト回避 |
| Sakura インスタンス種別 | 高火力 VRT (VM 型) | Ollama 常駐と同一 NW 参加を両立、DOK (コンテナ短時間) や PHY (ベアメタル大規模) は不向き |
| GPU プラン | L40S 48GB (時間貸し) | Qwen 3 32B (~20GB 4bit) に余裕、~500-700 円/h、必要時 boot / 停止時 shutdown |
| Primary モデル | Qwen 3 32B (dense) | Qwen 2.5 32B の後継、日本語品質改善、医療語彙は 32B dense が sweet spot |

## Architecture

```
┌────────────────────┐        SSH tunnel (11434 forward)              ┌─────────────────────────┐
│  Local Mac         │◄─────────────────────────────────────────────► │  Sakura GPU VM (VRT)    │
│                    │                                                │  L40S 48GB / Ubuntu 22  │
│  clinosim narrate  │                                                │                         │
│  --llm-config      │                                                │  ┌───────────────────┐  │
│    llm_service     │                                                │  │ Ollama systemd    │  │
│    .sakura.yaml    │                                                │  │  :11434 loopback  │  │
│                    │                                                │  │                   │  │
│  provider=ollama   │                                                │  │  qwen3:32b (primary) │
│  endpoint=         │                                                │  │  swallow:70b (alt)│  │
│    localhost:11434 │                                                │  │  llama3.3:70b     │  │
└────────────────────┘                                                │  └───────────────────┘  │
        │                                                             └─────────────────────────┘
        └── CIF / narrative files は local に留まる                     Ollama process 常駐
            (prompt のみ HTTPS で載る)                                  systemd で auto restart
```

**セキュリティ境界**:
- Ollama は `OLLAMA_HOST=127.0.0.1:11434` (loopback bind)、外部から直接接続不可
- Sakura packet filter で 11434 を閉じる (SSH tunnel 経由必須)
- 患者データ (CIF/narrative) は Local に残り、prompt のみ HTTP に載る
- 将来 IRIS 連携する際は Sakura スイッチ経由の閉域 (Phase 3 project 側で対応)

## 実装手順

### 1. インスタンス構築 (usacloud)

```bash
# 高火力 VRT (L40S) の起動 — 具体のプランコードは Sakura の現行ラインアップで確認
usacloud server create --zone=is1a \
    --name=clinosim-gpu-l40s \
    --os-type=ubuntu \
    --cpu=... --memory=... --gpu=l40s \
    --disk-size=100 \
    --ssh-key-ids=<existing-key-id>
```

**チェックポイント**:
- OS: Ubuntu 22.04 LTS (現行 Sakura テンプレ、Ollama は 22.04 で安定動作)
- ディスク: 100GB (モデル 20-45GB + OS + cache)
- SSH: 公開鍵で ubuntu ログイン
- パケットフィルタ: 22/tcp (SSH) のみ許可、11434 は閉じる

### 2. NVIDIA driver + CUDA

```bash
sudo apt update && sudo apt install -y nvidia-driver-550
sudo reboot
# 再起動後
nvidia-smi   # L40S 認識 + 48GB VRAM 確認
```

### 3. Ollama 導入 + loopback bind

```bash
curl -fsSL https://ollama.com/install.sh | sh
# systemd override で loopback bind
sudo systemctl edit ollama
# エディタで以下を追記:
#   [Service]
#   Environment="OLLAMA_HOST=127.0.0.1:11434"
sudo systemctl restart ollama
sudo systemctl status ollama   # active (running) 確認
```

### 4. モデル pull (Qwen 3 primary + 比較候補)

```bash
# Primary
ollama pull qwen3:32b-q4_K_M              # ~20GB、日本語医療 narrative primary

# 比較候補 (品質評価用に順次)
ollama pull qwen3:30b-a3b-q4_K_M          # ~18GB、MoE で推論高速、品質比較用
ollama pull llama3.3:70b-instruct-q4_K_M  # ~42GB、汎用最強、参照用
ollama pull swallow:70b-instruct-q4_K_M   # ~42GB、東工大 JA-tuned Llama、日本語 native

# 動作テスト
ollama run qwen3:32b-q4_K_M "1 行で: 患者は倦怠感を訴える"
```

**モデル選定基準** (別途評価):
- 日本語医療語彙の正確性 (Judgment task で人手評価)
- narrative の自然さ (Coherence / Fluency スコア)
- 推論速度 (t/s)
- Layer 2 cache hit rate に効く determinism (temperature=0 で安定性)

### 5. Local Mac から SSH tunnel

```bash
# 11434 を Sakura の 11434 に forward、-N でリモートコマンド実行なし
ssh -i ~/.ssh/sakura.pem -L 11434:127.0.0.1:11434 -N ubuntu@<sakura-ip> &

# 疎通確認
curl http://localhost:11434/api/tags                                          # Ollama native: モデル一覧
curl http://localhost:11434/v1/models                                         # OpenAI 互換: モデル一覧
curl -X POST http://localhost:11434/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"qwen3:32b-q4_K_M","messages":[{"role":"user","content":"test"}]}'
```

### 6. clinosim config: `clinosim/config/llm_service.sakura.yaml`

```yaml
# clinosim LLM Service Configuration — Sakura Cloud GPU (Ollama)
#
# Intended for Sakura VRT (L40S 48GB) hosting Ollama, accessed via SSH tunnel
# from local workstation.
#
# Prerequisites:
#   - SSH tunnel: ssh -L 11434:127.0.0.1:11434 -N ubuntu@<sakura-ip> &
#   - Ollama running on Sakura VM with qwen3:32b-q4_K_M pulled
#
# Usage:
#   clinosim narrate \
#       --cif-dir ./output/cif \
#       --llm-config clinosim/config/llm_service.sakura.yaml \
#       --version-id sakura_qwen3_32b_v1

judgment:
  mode: "template"
  provider: ""

narrative:
  mode: "llm"
  provider: "ollama"   # Ollama native /api/generate 経由
  ollama:
    endpoint: "http://localhost:11434"   # SSH tunnel 経由 (loopback)
    model: "qwen3:32b-q4_K_M"
  model_map:
    small:  "qwen3:32b-q4_K_M"
    medium: "qwen3:32b-q4_K_M"
    large:  "qwen3:32b-q4_K_M"
  timeout_seconds: 180
  retry_attempts: 2
  retry_backoff_seconds: 2

cache:
  enabled: true
  directory: "./.llm_cache/sakura"
  max_entries: 100000
```

**OpenAI 互換で叩く場合の代替 config** (provider が `openai` 対応なら):

```yaml
narrative:
  mode: "llm"
  provider: "openai"
  openai:
    base_url: "http://localhost:11434/v1"   # Ollama OpenAI 互換 endpoint
    api_key: "ollama"                        # 任意文字列で OK (Ollama は認証しない)
    model: "qwen3:32b-q4_K_M"
```

### 7. 動作検証プロトコル

```bash
# ミニマル検証 (JP p=1)
clinosim generate --country JP --population 1 --seed 42 --format cif -o /tmp/smoke
clinosim narrate --cif-dir /tmp/smoke/cif \
    --llm-config clinosim/config/llm_service.sakura.yaml \
    --version-id sakura_qwen3_32b_v1 --country JP --set-current

# 中規模 (p=100) — 品質評価 + 速度実測
clinosim generate --country JP --population 100 --seed 42 --format cif -o /tmp/eval100
clinosim narrate --cif-dir /tmp/eval100/cif \
    --llm-config clinosim/config/llm_service.sakura.yaml \
    --version-id sakura_qwen3_32b_v1 --country JP --set-current
# 期待: ~5-15 sec/call、fail 0%、cache hit で 2 回目は 10x 高速

# フル (p=10000) — cache 効きも含めた実運用シミュレート
# 予想実行時間: 検証時 4-8h、cache 効いた 2 回目以降 1-2h
```

## 判断ポイント (実施時の指針)

### コスト
- L40S 時間貸し: ~500-700 円/h (Sakura 現行料金要確認)
- 検証時 (フル p=10000, cold): 4-8h × 700 = ~2,800-5,600 円/回
- 実運用 (cache 効いた再実行): 1-2h × 700 = ~700-1,400 円/回
- 未使用時は shutdown で課金停止 (Sakura VRT は時間課金)

### セキュリティ
- 11434 を **絶対に外部公開しない**。必ず SSH tunnel or VPN 経由
- Sakura packet filter で 22 (SSH) のみ開放、11434 は閉
- CIF/narrative は local に残す (prompt のみ HTTP に載る、これは OK)
- 医療情報 3 省 2 ガイドライン相当の運用: Ollama process log には prompt 生データが残るので、テスト後は log purge 推奨

### 品質評価とモデル切替
- 初回は Qwen 3 32B で確定、品質不十分なら以下順に試す:
  1. Swallow 70B (東工大 JA-tuned) — 日本語 native、モデル切替は Ollama pull + config 変更のみ
  2. Llama 3.3 70B — 汎用最強、日本語○
  3. Qwen 3 30B-A3B (MoE) — 高速だが品質は 32B dense より劣る可能性
- モデル切替時は `--version-id` を変えて narrative version を分離、比較評価可能に

### Cache 運用
- Layer 2 (disk PromptCache) を **必ず有効化**、コスト 1/10
- cache dir: `./.llm_cache/sakura/` (default location)、`--set-current` で version 管理
- cache invalidation は prompt template 更新時のみ (temperature=0 前提)

## Deliverables

1. `docs/design-notes/2026-08-15-sakura-gpu-ollama-narrative.md` (この spec)
2. `clinosim/config/llm_service.sakura.yaml` (実施時に追加)
3. `docs/sakura_gpu_setup.md` (bedrock_setup.md と対になる HOW-TO、実施時に作成)
4. モデル品質評価結果 (実施時、別 doc に)

## 実施時の判断チェックリスト

- [ ] Sakura 現行の高火力 VRT ラインアップと L40S 実価格を確認
- [ ] Qwen 3 32B が Ollama library で `qwen3:32b-q4_K_M` として利用可能かを最新の Ollama モデルレジストリで確認 (release 名は変わりうる)
- [ ] clinosim の Ollama provider (既存) が `endpoint` + `model` 指定で動作することを既存テストで確認
- [ ] `clinosim/config/llm_service.sakura.yaml` を追加 + PR
- [ ] `docs/sakura_gpu_setup.md` を作成 (bedrock_setup.md を雛形に)
- [ ] p=1 smoke → p=100 品質評価 → 結果を design-notes に追記

## Follow-up 検討 (別 spec)

- **日本語医療 LLM モデルの継続評価**: 新モデル (Qwen 3.5, Swallow v3 等) 出るたびの comparison workflow 化
- **Sakura AI Engine との比較**: managed vs self-host のコスト/品質比較 (parent project `proj-iris-sakura-verification` Phase 3 と統合してもよい)
- **プロダクション運用**: 24/7 稼働、複数 VM の負荷分散、rate limit、監視 (Prometheus/Grafana) — 本 spec の out of scope
- **Bedrock 互換レイヤ (LiteLLM)**: 必要になった時点で別途評価
