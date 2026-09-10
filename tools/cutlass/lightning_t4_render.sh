#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo 'Usage: lightning_t4_render.sh INPUT_IMAGE "PROMPT" [OUTPUT_DIR]'
  exit 2
fi

INPUT_IMAGE="$1"
PROMPT="$2"
OUTPUT_DIR="${3:-$HOME/cutlass/output}"
ROOT="$HOME/cutlass"
WAN_DIR="$ROOT/Wan2.2"
MODEL_DIR="$ROOT/models/Wan2.2-TI2V-5B"

mkdir -p "$OUTPUT_DIR"
cd "$OUTPUT_DIR"

# T4/16GB path: keep text encoder and inactive model components off GPU.
python "$WAN_DIR/generate.py" \
  --task ti2v-5B \
  --size '704*1280' \
  --ckpt_dir "$MODEL_DIR" \
  --offload_model True \
  --convert_model_dtype \
  --t5_cpu \
  --image "$INPUT_IMAGE" \
  --prompt "$PROMPT"

echo 'CUTLASS RENDER COMPLETE'
find "$OUTPUT_DIR" -type f -name '*.mp4' -print
