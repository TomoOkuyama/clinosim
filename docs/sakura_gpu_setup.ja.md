# Sakura Cloud GPU + Ollama で Stage 2 を動かす

本ガイドは clinosim の Stage 2 (`narrate`) を **自ホスト Ollama
サーバ** (さくらのクラウド 高火力 VRT、L40S 48GB GPU VM) に対して
実行する手順を示します。`docs/bedrock_setup.ja.md` (AWS Bedrock
ルート) の対 — データ主権 / 医療情報 3 省 2 ガイドライン / コスト
予測性の観点でマネージド API を離れる場合に使用。

Design record: `docs/design-notes/2026-08-15-sakura-gpu-ollama-narrative.md`。

```
┌────────────────┐   SSH tunnel   ┌──────────────────────┐
│ local Mac /    │◄──────────────►│ Sakura GPU VM (is1a) │
│ workstation    │  11434 forward │  ├─ NVIDIA driver    │
│                │                │  ├─ Ollama systemd   │
│ clinosim       │                │  │   :11434 loopback │
│   narrate ───► │                │  └─ qwen3:32b        │
│   --llm-config │                │                      │
│   sakura.yaml  │                │                      │
└────────────────┘                └──────────────────────┘
     │                                       │
     └── CIF / narrative は local に留まる  └── Ollama process log は定期 purge
         (prompt のみ HTTP に載る)
```

データフロー: Stage 1 `simulate` → local。CIF ディレクトリを local
に置き、`narrate` の HTTP 呼出だけが SSH tunnel 越しに Sakura GPU
へ届く。prompt に PHI を載せる場合の運用上の注意は末尾を参照。

---

## 前提条件

- さくらのクラウドアカウント + API キー (usacloud CLI で使用)。
- 高火力 VRT (L40S 48GB) の利用申請が済んでいる (Sakura コントロール
  パネル「サーバ追加」→「高火力プラン」を確認)。
- ローカルの SSH 秘密鍵 (`ed25519` 推奨) と対応する公開鍵が Sakura
  に登録済み。
- Local workstation に clinosim + Python 3.11+。

---

## 1. Sakura GPU VM のプロビジョン (usacloud)

usacloud CLI + プロファイル整備は
[[sakura-cloud|entities/sakura-cloud]] / 参考 repo
`~/workspace/sakura-iris/docs/01-usacloud-setup.md` にまとまって
います。本セクションは要点のみ:

```bash
# usacloud プロファイル (既に iris-verify プロファイルがあれば流用可)
usacloud config create --name clinosim-gpu \
    --token <SAKURA_API_TOKEN> --secret <SAKURA_API_SECRET> \
    --zone is1a --use

# 高火力 VRT L40S の起動 (プランコードは Sakura の現行ラインアップで
# 都度確認。--fake を付ければ dry-run 検証可能)
usacloud server create -y --zone=is1a \
    --name=clinosim-gpu-l40s \
    --disk-source-archive-name-selectors=Ubuntu 22.04 \
    --disk-size=100 \
    --ssh-key-ids=<existing-ssh-key-id> \
    --plan=<gpu-l40s-plan-code>
```

**Sakura 固有の落とし穴** (詳細は sakura-iris
`docs/90-troubleshooting.md`):

- 高火力 VRT は `is1a` のみ提供。他ゾーンとは L2 ブリッジが必要。
- パケットフィルタは **ステートレス**。エフェメラルポート
  32768-61000 の TCP/UDP を戻り用に明示許可要 (SSH 応答含む)。
- `--fake --fake-store <path>` で課金なしオプション検証。破壊的
  スクリプトの sanity check に有効。
- 非対話環境では `-y` 必須 (create / delete / shutdown)。
- アーカイブ ID はゾーン & リリースごとに変わる。名前指定
  (`--disk-source-archive-name-selectors=Ubuntu 22.04`) が安定。

## 2. パケットフィルタ (最重要セキュリティ設定)

```bash
# 22/tcp (SSH) のみ許可、11434 は絶対に開けない
usacloud packet-filter create -y --zone=is1a --name=clinosim-gpu-pf \
    --description="clinosim GPU VM: SSH only"
usacloud packet-filter-rule add -y --zone=is1a --packet-filter=clinosim-gpu-pf \
    --protocol=tcp --destination-port=22 --action=allow
# エフェメラル戻り (SSH 応答等)
usacloud packet-filter-rule add -y --zone=is1a --packet-filter=clinosim-gpu-pf \
    --protocol=tcp --source-port=32768-61000 --action=allow
usacloud packet-filter-rule add -y --zone=is1a --packet-filter=clinosim-gpu-pf \
    --protocol=udp --source-port=32768-61000 --action=allow
# NIC に適用
usacloud interface update -y --zone=is1a --id=<nic-id> \
    --packet-filter-id=<packet-filter-id>
```

Ollama の 11434 は SSH tunnel 越しでしか届かない。**直接公開したら
患者データが露出する可能性がある** ので、この設定は skip しない。

---

## 3. NVIDIA driver + CUDA

VM に SSH 接続 (`ssh -i ~/.ssh/sakura.pem ubuntu@<sakura-ip>`) 後:

```bash
sudo apt update && sudo apt install -y nvidia-driver-550
sudo reboot
# 再起動後の SSH 再接続後
nvidia-smi   # L40S + 48GB VRAM の認識確認
```

---

## 4. Ollama のインストール + loopback バインド

```bash
curl -fsSL https://ollama.com/install.sh | sh

# systemd override で 127.0.0.1 バインド (デフォルトは 0.0.0.0)
sudo systemctl edit ollama
# エディタで以下を追記して保存:
#   [Service]
#   Environment="OLLAMA_HOST=127.0.0.1:11434"

sudo systemctl restart ollama
sudo systemctl status ollama   # active (running) 確認
ss -ntlp | grep 11434          # 127.0.0.1:11434 で listen していれば OK
```

**確認**: `ss` 出力で `0.0.0.0:11434` になっている場合は override
が効いていない → `sudo systemctl cat ollama` で override の反映を
確認。

---

## 5. モデル pull

```bash
# Primary (日本語医療 narrative)
ollama pull qwen3:32b-q4_K_M              # ~20 GB、L40S 48GB に余裕あり

# 比較候補 (品質評価用に順次)
# ollama pull swallow:70b-instruct-q4_K_M   # ~42 GB、東工大 JA-tuned Llama
# ollama pull llama3.3:70b-instruct-q4_K_M  # ~42 GB、汎用最強
# ollama pull qwen3:30b-a3b-q4_K_M          # ~18 GB、MoE 高速

# 動作確認
ollama run qwen3:32b-q4_K_M "1 行で: 患者は倦怠感を訴える"
```

**モデル tag は Ollama library のリリースごとに変わる**。上記が pull
できない場合は `ollama search qwen3` で最新 tag を確認。

---

## 6. ローカルワークステーションからの SSH tunnel

```bash
# Local Mac の 11434 を Sakura の 11434 にフォワード (バックグラウンド常駐)
ssh -i ~/.ssh/sakura.pem -L 11434:127.0.0.1:11434 -N ubuntu@<sakura-ip> &

# 疎通確認
curl http://localhost:11434/api/tags                    # Ollama native: モデル一覧
curl http://localhost:11434/v1/models                   # OpenAI 互換: モデル一覧
```

trouble: `curl: (52) Empty reply from server` → Ollama が 0.0.0.0
バインドで tunnel を無視している可能性。VM 側で
`ss -ntlp | grep 11434` の再確認。

---

## 7. Sakura Ollama に対して `clinosim narrate` を実行

```bash
# ミニマル smoke (JP p=1) — VM 1 回起動して SSH tunnel 常駐前提で ~1 min
clinosim simulate --country JP --population 1 --seed 42 --format cif \
    -o /tmp/sakura-smoke
clinosim narrate \
    --cif-dir /tmp/sakura-smoke/cif \
    --llm-config clinosim/config/llm_service.sakura.yaml \
    --version-id sakura_qwen3_32b_smoke \
    --country JP \
    --set-current

# 中規模 (p=100) — 品質評価 + 速度実測
clinosim simulate --country JP --population 100 --seed 42 --format cif \
    -o /tmp/sakura-eval100
clinosim narrate \
    --cif-dir /tmp/sakura-eval100/cif \
    --llm-config clinosim/config/llm_service.sakura.yaml \
    --version-id sakura_qwen3_32b_eval100 \
    --country JP \
    --set-current
```

期待: ~5-15 sec/call、fail 0%、cache hit で 2 回目は 10x 高速。
manifest.json の `llm_cost_report.generator_llm_docs` が期待数に一致
し、`generator_fallback_docs` が 0 なら bundle strategy の JSON
parse は成功している。

---

## 8. 停止 (課金対策)

```bash
# 未使用時は VM shutdown で課金停止 (削除ではないので再起動時に model の
# 再 pull 不要)
usacloud server shutdown -y --zone=is1a clinosim-gpu-l40s

# 再開
usacloud server boot -y --zone=is1a clinosim-gpu-l40s
```

削除は `--with-disks` を忘れると disk 課金が残る (Sakura 全般):

```bash
usacloud server delete -y --zone=is1a --with-disks clinosim-gpu-l40s
```

---

## 運用上の注意

### プロンプトログの取扱

Ollama process log には prompt 生データ (患者情報を含む narrative
seed + context) が残る。医療情報 3 省 2 ガイドライン相当の運用を
想定するなら:

- `journalctl` の retention を短めに (`/etc/systemd/journald.conf`
  の `MaxRetentionSec=1day` 等)
- テスト後は
  `sudo journalctl --rotate && sudo journalctl --vacuum-time=1s`
  で明示的に purge
- Ollama の debug ログを OFF (`OLLAMA_DEBUG=0` — デフォルト)

### 品質評価とモデル切替

初回は Qwen 3 32B (`qwen3:32b-q4_K_M`) で確定。narrative の日本語
医療語彙が不十分と判断した場合、以下の順で試す:

1. **Swallow 70B** (東工大 JA-tuned Llama) — 日本語 native、モデル
   切替は `ollama pull swallow:70b-instruct-q4_K_M` + config
   `model:` 書換のみ。`--version-id` を変えれば比較評価可能。
2. **Llama 3.3 70B** — 汎用最強、日本語 ○。
3. **Qwen 3 30B-A3B (MoE)** — 高速だが品質は 32B dense より劣る可能
   性あり。速度優先の運用に。

### コスト目安

- L40S 時間貸し: **~500-700 円/h** (Sakura の現行料金要確認)
- 検証時 (p=10000、cold、Layer 2 cache miss): 4-8h × 700 =
  **~2,800-5,600 円/回**
- 実運用 (cache 効いた再実行): 1-2h × 700 = **~700-1,400 円/回**
- 未使用時 shutdown で課金停止 (時間課金)

### Cache 運用

- Layer 2 (disk PromptCache、`./.llm_cache/sakura/`) は **必ず有効化**。
  cold と warm でコストが 1 桁変わる。
- `temperature=0` 前提の determinism を保つ。
- cache invalidation は prompt template
  (`clinosim/modules/llm_service/prompts/{en,ja}/narrative_seed_bundle.yaml`)
  を編集した時のみ。

---

## 関連

- `docs/design-notes/2026-08-15-sakura-gpu-ollama-narrative.md` —
  設計 spec (design of record)。
- `docs/bedrock_setup.ja.md` — AWS Bedrock ルート (対のマネージド
  API 版)。
- `clinosim/config/llm_service.sakura.yaml` — 本ガイド用の config。
- Sakura 固有の知見 (obsidian): [[entities/sakura-cloud]]。
- 一般 pattern (obsidian): [[concepts/gpu-instance-llm-hosting-pattern]]。
- 参考実装 repo: `~/workspace/sakura-iris/` の `docs/01-04-*` と
  `scripts/10-11-*`、`scripts/52-open-iris-hl7.sh`。
