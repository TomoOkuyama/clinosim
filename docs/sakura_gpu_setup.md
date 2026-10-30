# Sakura Cloud GPU + Ollama setup for Stage 2

This guide shows how to run clinosim's Stage 2 (`narrate`) against a
**self-hosted Ollama server** on Sakura Cloud (さくらのクラウド)
高火力 VRT (high-performance GPU VM, L40S 48GB). Companion to
`docs/bedrock_setup.md` (the AWS Bedrock route) — use this when data
sovereignty, Japan's medical-information security guidelines (the
"3 ministries, 2 guidelines", 医療情報 3 省 2 ガイドライン) or cost
predictability push you off managed APIs.

Design record: `docs/design-notes/2026-08-15-sakura-gpu-ollama-narrative.md`.

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
     └── CIF / narratives stay local         └── Ollama process log purged regularly
         (only prompts travel over HTTP)
```

Data flow: Stage 1 `simulate` runs locally. The CIF directory stays on
the local machine; only `narrate`'s HTTP calls reach the Sakura GPU
through the SSH tunnel. See the end of this guide for operational
notes when prompts carry PHI.

---

## Prerequisites

- A Sakura Cloud account and API key (used by the usacloud CLI).
- Access to 高火力 VRT (L40S 48GB) approved (check under "Add server"
  → "High-performance plan" (高火力プラン) in the Sakura control
  panel).
- A local SSH private key (`ed25519` recommended) whose public key is
  registered with Sakura.
- clinosim + Python 3.11+ on the local workstation.

---

## 1. Provision the Sakura GPU VM (usacloud)

Installing the usacloud CLI and setting up its profile are covered in
the official usacloud documentation (https://docs.usacloud.jp/usacloud/).
This section lists only the essentials:

```bash
# usacloud profile (an existing profile can be reused)
usacloud config create --name clinosim-gpu \
    --token <SAKURA_API_TOKEN> --secret <SAKURA_API_SECRET> \
    --zone is1a --use

# Launch a 高火力 VRT L40S (check the plan code against Sakura's current
# lineup each time; add --fake for a dry-run check)
usacloud server create -y --zone=is1a \
    --name=clinosim-gpu-l40s \
    --disk-source-archive-name-selectors=Ubuntu 22.04 \
    --disk-size=100 \
    --ssh-key-ids=<existing-ssh-key-id> \
    --plan=<gpu-l40s-plan-code>
```

**Sakura-specific pitfalls**:

- 高火力 VRT is offered only in `is1a`. Reaching other zones needs an
  L2 bridge.
- Packet filters are **stateless**. TCP/UDP on the ephemeral ports
  32768-61000 must be explicitly allowed for return traffic
  (including SSH replies).
- `--fake --fake-store <path>` validates options without billing.
  Useful for sanity-checking destructive scripts.
- Non-interactive environments need `-y` (create / delete / shutdown).
- Archive IDs change per zone and release. Selecting by name
  (`--disk-source-archive-name-selectors=Ubuntu 22.04`) is stable.

## 2. Packet filter (the most important security setting)

```bash
# Allow 22/tcp (SSH) only; never open 11434
usacloud packet-filter create -y --zone=is1a --name=clinosim-gpu-pf \
    --description="clinosim GPU VM: SSH only"
usacloud packet-filter-rule add -y --zone=is1a --packet-filter=clinosim-gpu-pf \
    --protocol=tcp --destination-port=22 --action=allow
# Ephemeral return traffic (SSH replies etc.)
usacloud packet-filter-rule add -y --zone=is1a --packet-filter=clinosim-gpu-pf \
    --protocol=tcp --source-port=32768-61000 --action=allow
usacloud packet-filter-rule add -y --zone=is1a --packet-filter=clinosim-gpu-pf \
    --protocol=udp --source-port=32768-61000 --action=allow
# Apply to the NIC
usacloud interface update -y --zone=is1a --id=<nic-id> \
    --packet-filter-id=<packet-filter-id>
```

Ollama's port 11434 must be reachable only through the SSH tunnel.
**Exposing it directly can expose patient data**, so do not skip this
step.

---

## 3. NVIDIA driver + CUDA

After connecting to the VM over SSH (`ssh -i ~/.ssh/sakura.pem ubuntu@<sakura-ip>`):

```bash
sudo apt update && sudo apt install -y nvidia-driver-550
sudo reboot
# After reconnecting over SSH
nvidia-smi   # confirm the L40S with 48GB VRAM is detected
```

---

## 4. Install Ollama + loopback bind

```bash
curl -fsSL https://ollama.com/install.sh | sh

# Bind to 127.0.0.1 via a systemd override (the default is 0.0.0.0)
sudo systemctl edit ollama
# In the editor, add the following and save:
#   [Service]
#   Environment="OLLAMA_HOST=127.0.0.1:11434"

sudo systemctl restart ollama
sudo systemctl status ollama   # confirm active (running)
ss -ntlp | grep 11434          # OK if listening on 127.0.0.1:11434
```

**Check**: if `ss` shows `0.0.0.0:11434`, the override has not taken
effect — inspect it with `sudo systemctl cat ollama`.

---

## 5. Pull models

```bash
# Primary (Japanese clinical narratives)
ollama pull qwen3:32b-q4_K_M              # ~20 GB, fits comfortably in the L40S's 48GB

# Comparison candidates (pull one at a time for quality evaluation)
# ollama pull swallow:70b-instruct-q4_K_M   # ~42 GB, Tokyo Tech JA-tuned Llama
# ollama pull llama3.3:70b-instruct-q4_K_M  # ~42 GB, strongest general-purpose option
# ollama pull qwen3:30b-a3b-q4_K_M          # ~18 GB, fast MoE

# Smoke test (Japanese prompt: "In one line: the patient complains of fatigue")
ollama run qwen3:32b-q4_K_M "1 行で: 患者は倦怠感を訴える"
```

**Model tags change with Ollama library releases**. If the tags above
cannot be pulled, check the latest tag with `ollama search qwen3`.

---

## 6. SSH tunnel from local workstation

```bash
# Forward local port 11434 to Sakura's 11434 (runs in the background)
ssh -i ~/.ssh/sakura.pem -L 11434:127.0.0.1:11434 -N ubuntu@<sakura-ip> &

# Connectivity check
curl http://localhost:11434/api/tags                    # Ollama native: model list
curl http://localhost:11434/v1/models                   # OpenAI-compatible: model list
```

Troubleshooting: `curl: (52) Empty reply from server` → Ollama may be
bound to 0.0.0.0 and bypassing the tunnel. Re-check
`ss -ntlp | grep 11434` on the VM.

---

## 7. Run `clinosim narrate` against Sakura Ollama

```bash
# Minimal smoke (JP p=1) — ~1 min, assuming the VM is up and the SSH tunnel is running
clinosim simulate --country JP --population 1 --seed 42 --format cif \
    -o /tmp/sakura-smoke
clinosim narrate \
    --cif-dir /tmp/sakura-smoke/cif \
    --provider ollama \
    --llm-config clinosim/config/llm_service.sakura.yaml \
    --version-id sakura_qwen3_32b_smoke \
    --country JP \
    --set-current

# Medium (p=100) — quality evaluation + measured throughput
clinosim simulate --country JP --population 100 --seed 42 --format cif \
    -o /tmp/sakura-eval100
clinosim narrate \
    --cif-dir /tmp/sakura-eval100/cif \
    --provider ollama \
    --llm-config clinosim/config/llm_service.sakura.yaml \
    --version-id sakura_qwen3_32b_eval100 \
    --country JP \
    --set-current
```

Expected: ~5-15 sec/call, 0% failures, and a second run ~10x faster on
cache hits. If `llm_cost_report.generator_llm_docs` in manifest.json
matches the expected count and `generator_fallback_docs` is 0, the
bundle strategy's JSON parsing succeeded.

---

## 8. Stopping (to control cost)

```bash
# Shut the VM down when idle to stop billing (it is not deleted, so the
# model does not need to be pulled again after reboot)
usacloud server shutdown -y --zone=is1a clinosim-gpu-l40s

# Resume
usacloud server boot -y --zone=is1a clinosim-gpu-l40s
```

When deleting, forgetting `--with-disks` leaves disk charges running
(true across Sakura):

```bash
usacloud server delete -y --zone=is1a --with-disks clinosim-gpu-l40s
```

---

## Operational notes

### Handling prompt logs

The Ollama process log keeps raw prompts (narrative seed + context,
including patient information). If you operate under the equivalent
of Japan's medical-information security guidelines:

- Keep the `journalctl` retention short (e.g. `MaxRetentionSec=1day`
  in `/etc/systemd/journald.conf`)
- Purge explicitly after testing with
  `sudo journalctl --rotate && sudo journalctl --vacuum-time=1s`
- Keep Ollama's debug log OFF (`OLLAMA_DEBUG=0` — the default)

### Quality evaluation and switching models

Qwen 3 32B (`qwen3:32b-q4_K_M`) is the initial choice. If the
Japanese clinical vocabulary in the narratives is judged insufficient,
try the following in order:

1. **Swallow 70B** (Tokyo Tech JA-tuned
   Llama) — native Japanese; switching only takes
   `ollama pull swallow:70b-instruct-q4_K_M` plus editing `model:` in
   the config. Use a different `--version-id` to compare runs.
2. **Llama 3.3 70B** — strongest general-purpose option; good Japanese.
3. **Qwen 3 30B-A3B (MoE)** — fast, but quality may be below the 32B
   dense model. For speed-first operation.

### Cost estimates

- L40S hourly rental: **~500-700 JPY/h** (check Sakura's current pricing)
- Validation run (p=10000, cold, Layer 2 cache miss): 4-8h × 700 =
  **~2,800-5,600 JPY/run**
- Production re-runs (cache warm): 1-2h × 700 = **~700-1,400 JPY/run**
- Shutting down when idle stops billing (hourly billing)

### Cache operation

- **Always enable** Layer 2 (disk PromptCache, `./.llm_cache/sakura/`).
  Cold vs. warm cost differs by an order of magnitude.
- Keep the determinism that assumes `temperature=0`.
- Invalidate the cache only when you edit the prompt template
  (`clinosim/modules/llm_service/prompts/{en,ja}/narrative_seed_bundle.yaml`).

---

## Related

- `docs/design-notes/2026-08-15-sakura-gpu-ollama-narrative.md` —
  design spec (design of record).
- `docs/bedrock_setup.md` — the AWS Bedrock route (the managed-API
  counterpart).
- `clinosim/config/llm_service.sakura.yaml` — the config used by this
  guide.
