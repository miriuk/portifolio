#!/usr/bin/env bash
# Kronos (github.com/shiyu-coder/Kronos, MIT) is not on PyPI: its model code
# comes from the repository, at a pinned commit so a bench run today and one
# next year use the same code. The weights come from the Hugging Face hub
# the first time a model is loaded.
#
#   pip install -e ".[forecast,kronos]"   # PyTorch, einops, huggingface_hub, safetensors
#   bash scripts/install_kronos.sh        # the model code, into ./Kronos
#   KRONOS_PATH="$PWD/Kronos" cryptoarena forecast --models kronos-mini,kronos,kronos-base ...
set -euo pipefail

KRONOS_REF="${KRONOS_REF:-67b630e67f6a18c9e9be918d9b4337c960db1e9a}"   # 13/04/2026
dest="${1:-Kronos}"

if [ -d "$dest/.git" ]; then
  have=$(git -C "$dest" rev-parse HEAD)
  if [ "$have" = "$KRONOS_REF" ]; then
    echo "Kronos already at $KRONOS_REF in $dest"
    exit 0
  fi
fi
rm -rf "$dest.tmp"
git init -q "$dest.tmp"
git -C "$dest.tmp" fetch -q --depth 1 https://github.com/shiyu-coder/Kronos.git "$KRONOS_REF"
git -C "$dest.tmp" checkout -q FETCH_HEAD
rm -rf "$dest"
mv "$dest.tmp" "$dest"
echo "Kronos $KRONOS_REF in $dest; set KRONOS_PATH=$(cd "$dest" && pwd)"
