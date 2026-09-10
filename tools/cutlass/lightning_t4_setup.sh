#!/usr/bin/env bash
set -euo pipefail

# Cutlass / Lightning AI T4 bootstrap.
# Keeps the existing Modal renderer intact; this is the no-card T4 path.

ROOT="$HOME/cutlass"
WAN_DIR="$ROOT/Wan2.2"
MODEL_DIR="$ROOT/models/Wan2.2-TI2V-5B"
VENV="$ROOT/.venv"

mkdir -p "$ROOT/models" "$ROOT/output"

if [ ! -d "$WAN_DIR/.git" ]; then
  git clone --depth 1 https://github.com/Wan-Video/Wan2.2.git "$WAN_DIR"
fi

python3 -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install --upgrade pip wheel setuptools

# Do not replace Lightning's working CUDA driver. Install the Python stack only.
pip install \
  'torch>=2.4.0' torchvision torchaudio \
  'opencv-python-headless>=4.9.0.80' \
  'diffusers>=0.31.0' \
  'transformers>=4.49.0,<=4.51.3' \
  'tokenizers>=0.20.3' \
  'accelerate>=1.1.1' tqdm 'imageio[ffmpeg]' easydict ftfy \
  dashscope imageio-ffmpeg 'huggingface_hub[hf_transfer]' \
  'numpy>=1.23.5,<2'

python - <<'PY'
import torch
print('CUTLASS CUDA:', torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit('CUDA is not available to PyTorch')
print('CUTLASS GPU:', torch.cuda.get_device_name(0))
print('CUTLASS VRAM_GB:', round(torch.cuda.get_device_properties(0).total_memory/1024**3, 2))
PY

# Download once into persistent Studio storage. This is the large step.
python - <<'PY'
from huggingface_hub import snapshot_download
from pathlib import Path
p = Path.home() / 'cutlass/models/Wan2.2-TI2V-5B'
p.mkdir(parents=True, exist_ok=True)
snapshot_download('Wan-AI/Wan2.2-TI2V-5B', local_dir=str(p))
print('CUTLASS MODEL READY:', p)
PY

echo 'CUTLASS T4 READY'
echo "Wan:   $WAN_DIR"
echo "Model: $MODEL_DIR"
echo "Venv:  $VENV"
