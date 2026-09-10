import base64
import os
import subprocess
import tempfile
from pathlib import Path

import modal

APP_NAME = "dead-slot-cutlass"
MODEL_ID = "Wan-AI/Wan2.2-TI2V-5B"
MODEL_DIR = Path("/models/Wan2.2-TI2V-5B")
WAN_DIR = Path("/opt/Wan2.2")

app = modal.App(APP_NAME)
models = modal.Volume.from_name("dead-slot-wan-models", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg")
    .pip_install(
        "torch>=2.4.0",
        "torchvision>=0.19.0",
        "torchaudio",
        "opencv-python-headless>=4.9.0.80",
        "diffusers>=0.31.0",
        "transformers>=4.49.0,<=4.51.3",
        "tokenizers>=0.20.3",
        "accelerate>=1.1.1",
        "tqdm",
        "imageio[ffmpeg]",
        "easydict",
        "ftfy",
        "dashscope",
        "imageio-ffmpeg",
        "huggingface_hub[hf_transfer]",
        "numpy>=1.23.5,<2",
    )
    .run_commands(
        "git clone --depth 1 https://github.com/Wan-Video/Wan2.2.git /opt/Wan2.2"
    )
)


def _ensure_model() -> None:
    from huggingface_hub import snapshot_download

    if MODEL_DIR.exists() and any(MODEL_DIR.iterdir()):
        return
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        MODEL_ID,
        local_dir=str(MODEL_DIR),
        local_dir_use_symlinks=False,
    )
    models.commit()


@app.function(
    image=image,
    gpu="L40S",
    volumes={"/models": models},
    timeout=60 * 45,
    scaledown_window=120,
)
def render(image_bytes: bytes, prompt: str, size: str = "704*1280") -> bytes:
    """Render one Wan 2.2 TI2V clip and return MP4 bytes."""
    _ensure_model()

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        source = work / "input.png"
        source.write_bytes(image_bytes)

        cmd = [
            "python",
            str(WAN_DIR / "generate.py"),
            "--task", "ti2v-5B",
            "--size", size,
            "--ckpt_dir", str(MODEL_DIR),
            "--offload_model", "True",
            "--convert_model_dtype",
            "--t5_cpu",
            "--image", str(source),
            "--prompt", prompt,
        ]
        subprocess.run(cmd, cwd=str(work), check=True)

        videos = sorted(work.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if not videos:
            raise RuntimeError("Wan completed without producing an MP4")
        return videos[-1].read_bytes()


@app.function(image=modal.Image.debian_slim().pip_install("fastapi"))
@modal.fastapi_endpoint(method="POST", requires_proxy_auth=True, docs=False)
def render_endpoint(payload: dict):
    """Authenticated HTTP bridge. Payload: image_b64, prompt, optional size."""
    image_b64 = payload.get("image_b64")
    prompt = payload.get("prompt")
    if not image_b64 or not prompt:
        return {"ok": False, "error": "image_b64 and prompt are required"}

    video = render.remote(
        base64.b64decode(image_b64),
        prompt,
        payload.get("size", "704*1280"),
    )
    return {
        "ok": True,
        "video_b64": base64.b64encode(video).decode("ascii"),
    }


@app.local_entrypoint()
def main(input: str, prompt: str, output: str = "dead_slot_shot.mp4"):
    source = Path(input)
    result = render.remote(source.read_bytes(), prompt)
    Path(output).write_bytes(result)
    print(f"READY: {output}")
