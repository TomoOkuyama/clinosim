#!/usr/bin/env bash
# verify/rebuild_venv_pip.sh — Plan B fallback for Boot 3+ if cache cleanup
# alone doesn't fix the nvcc error.
#
# Rebuilds ~/vllm-env with plain pip (not uv), pinning to vllm 0.27.1
# which is what the S117 successful run used. This eliminates the uv
# install-drift hypothesis from Failed Run 2's postmortem.
#
# Time: ~15-20 min for downloads on Sakura network. Should be included
# in a full billing hour if triggered.

set -euo pipefail

echo "=== Rebuilding ~/vllm-env with plain pip @ $(date -u +%FT%TZ) ==="

# Preserve caches (Qwen model, torch caches, etc.) — only vllm-env itself
# is nuked.
echo "--- 1. Backup old venv path (just in case) ---"
if [ -d "$HOME/vllm-env" ]; then
    mv "$HOME/vllm-env" "$HOME/vllm-env.uv-broken.$(date +%s)"
    echo "old venv preserved for postmortem"
fi

echo "--- 2. Fresh venv with system python ---"
python3.12 -m venv "$HOME/vllm-env"
source "$HOME/vllm-env/bin/activate"
python -m pip install --upgrade pip setuptools wheel

echo "--- 3. Pip install vllm (pinned to 0.27.1 = S117 verified) ---"
# Pin the exact vLLM that S117 used. Downstream deps (torch, xformers,
# flash-attn, nvidia-cu*) will be resolved by pip's default resolver
# from PyPI wheels — pip's resolution differs from uv's on some deps.
pip install "vllm==0.27.1"

echo "--- 4. Pip install clinosim (editable) ---"
if [ -d "$HOME/clinosim" ]; then
    pip install -e "$HOME/clinosim"
else
    echo "WARNING: ~/clinosim not found — clone or symlink first"
fi

echo "--- 5. Sanity check ---"
python -c "import clinosim; print(f'clinosim {clinosim.__version__}')"
vllm --version 2>&1 | head -3
python -c "import torch; print(f'torch {torch.__version__}, CUDA {torch.version.cuda}, available: {torch.cuda.is_available()}')"

echo "=== Done @ $(date -u +%FT%TZ) ==="
echo "→ Now retry vLLM startup. Cache-cold + pip-clean environment."
