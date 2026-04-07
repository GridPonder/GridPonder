#!/usr/bin/env python3
"""
GridPonder tile generator.

Generates game-ready tile and sprite images from natural language descriptions.
Uses SDXL-Turbo + pixel-art-xl LoRA for pixel art and retro styles.
Single tiles use text2img; animation sequences (--count > 1) use img2img
conditioning on frame 1 so all frames share the same character and palette.

Works on Apple Silicon (MPS), CUDA, or CPU.
Venv: platform/tools/tile-gen/.venv  (system-site-packages, inherits torch)

Usage examples:
  python generate_tile.py "green grass tile"
  python generate_tile.py "stone wall tile" --style retro --size 64
  python generate_tile.py "water surface" --style pixel_art --size 128
  python generate_tile.py "rabbit running right" --count 3 --size 96
  python generate_tile.py "explosion" --count 4 --style cartoon --size 64
"""

import argparse
import sys
import warnings
from pathlib import Path

import torch
from PIL import Image

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SDXL_TURBO   = "stabilityai/sdxl-turbo"
LORA_REPO    = "nerijs/pixel-art-xl"
LORA_FILE    = "pixel-art-xl.safetensors"
LORA_ADAPTER = "default_0"
LORA_SCALE   = 0.9   # strength of pixel-art style pull

GEN_SIZE = 512  # always generate at 512x512, downscale afterwards

# Styles that activate the pixel-art LoRA
LORA_STYLES = {"pixel_art", "retro"}

STYLE_SUFFIX = {
    "pixel_art": (
        "pixel_art, pixel art game sprite, 16-bit style, flat colors, "
        "crisp pixel edges, retro video game tile, isolated on white background"
    ),
    "retro": (
        "pixel_art, 8-bit retro pixel art, NES/SNES style, very limited color "
        "palette, crisp square pixels, classic arcade aesthetic, isolated tile"
    ),
    "cartoon": (
        "2D cartoon game tile, flat colors, bold clean outlines, "
        "mobile game art style, isolated on white background, simple and clear"
    ),
    "default": (
        "2D game tile, flat illustration, clean edges, game asset, "
        "isolated on white background, simple and readable at small size"
    ),
}

NEGATIVE = (
    "multiple characters, sprite sheet, photorealistic, 3D render, blurry, "
    "noisy, text, watermark, accessories, busy background, smooth gradients"
)

RESAMPLE = {
    "pixel_art": Image.NEAREST,
    "retro":     Image.NEAREST,
    "cartoon":   Image.LANCZOS,
    "default":   Image.LANCZOS,
}

# Per-frame pose hints injected when count > 1
FRAME_HINTS = [
    "first frame, idle standing pose",
    "second frame, mid-stride, one leg forward",
    "third frame, full leap, both feet off ground",
    "fourth frame, landing, legs bent",
]


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------

def get_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


# ---------------------------------------------------------------------------
# Pipeline loading
# ---------------------------------------------------------------------------

def load_pipelines(style: str, device: str):
    """Return (txt2img_pipe, img2img_pipe). img2img shares weights with txt2img."""
    from diffusers import AutoPipelineForText2Image, AutoPipelineForImage2Image

    dtype = torch.float16 if device != "cpu" else torch.float32
    variant = "fp16" if device != "cpu" else None

    print(f"[tile-gen] Loading SDXL-Turbo on {device} …", file=sys.stderr)
    txt2img = AutoPipelineForText2Image.from_pretrained(
        SDXL_TURBO, torch_dtype=dtype, variant=variant
    ).to(device)

    if style in LORA_STYLES:
        print("[tile-gen] Loading pixel-art LoRA …", file=sys.stderr)
        txt2img.load_lora_weights(LORA_REPO, weight_name=LORA_FILE)
        txt2img.set_adapters(LORA_ADAPTER, adapter_weights=LORA_SCALE)

    img2img = AutoPipelineForImage2Image.from_pipe(txt2img)

    print("[tile-gen] Ready.", file=sys.stderr)
    return txt2img, img2img


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_prompt(user_prompt: str, style: str, frame_index: int, total_frames: int) -> str:
    suffix = STYLE_SUFFIX.get(style, STYLE_SUFFIX["default"])
    prompt = f"{user_prompt}, {suffix}"
    if total_frames > 1:
        hint = FRAME_HINTS[frame_index] if frame_index < len(FRAME_HINTS) \
               else f"animation frame {frame_index + 1} of {total_frames}"
        prompt += f", {hint}"
    return prompt


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate_tiles(
    txt2img,
    img2img,
    user_prompt: str,
    style: str,
    count: int,
    target_size: int,
    anim_strength: float,
    output_dir: Path,
    base_name: str,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    resample = RESAMPLE.get(style, Image.LANCZOS)
    saved: list[Path] = []
    reference: Image.Image | None = None

    for i in range(count):
        label = f"frame {i + 1}/{count}" if count > 1 else "tile"
        prompt = build_prompt(user_prompt, style, i, count)
        print(f"[tile-gen] Generating {label} …", file=sys.stderr)
        print(f"[tile-gen]   {prompt}", file=sys.stderr)

        if i == 0 or reference is None:
            # Frame 1 (or single tile): pure text2img
            result = txt2img(
                prompt=prompt,
                negative_prompt=NEGATIVE,
                num_inference_steps=4,
                guidance_scale=0.0,
                width=GEN_SIZE,
                height=GEN_SIZE,
            )
        else:
            # Subsequent frames: img2img conditioned on frame 1
            result = img2img(
                prompt=prompt,
                negative_prompt=NEGATIVE,
                image=reference,
                strength=anim_strength,
                num_inference_steps=4,
                guidance_scale=0.0,
            )

        img: Image.Image = result.images[0]

        # Keep frame 1 as the reference for all subsequent frames
        if i == 0:
            reference = img

        # Downscale to target size
        if target_size < GEN_SIZE:
            img = img.resize((target_size, target_size), resample)

        suffix = f"_{i + 1:02d}" if count > 1 else ""
        out_path = output_dir / f"{base_name}{suffix}.png"
        img.save(out_path)
        print(f"[tile-gen] Saved: {out_path}", file=sys.stderr)
        saved.append(out_path)

    return saved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate game tile/sprite images from text using local AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("prompt",
        help="Natural language description, e.g. 'green grass tile'")
    parser.add_argument("--size", type=int, default=64,
        help="Target tile size in pixels, square (default: 64)")
    parser.add_argument("--count", type=int, default=1,
        help="Number of tiles/animation frames to generate (default: 1)")
    parser.add_argument("--style", default="pixel_art",
        choices=list(STYLE_SUFFIX.keys()),
        help="Visual style preset (default: pixel_art)")
    parser.add_argument("--strength", type=float, default=0.75,
        help="img2img strength for animation frames 2+ (0.0–1.0, default: 0.75). "
             "Lower = more similar to frame 1; higher = more pose variation.")
    parser.add_argument("--output", type=Path, default=Path("."),
        help="Output directory (default: current directory)")
    parser.add_argument("--name", default="tile",
        help="Base filename without extension (default: tile)")
    args = parser.parse_args()

    device = get_device()
    txt2img, img2img = load_pipelines(args.style, device)

    saved = generate_tiles(
        txt2img=txt2img,
        img2img=img2img,
        user_prompt=args.prompt,
        style=args.style,
        count=args.count,
        target_size=args.size,
        anim_strength=args.strength,
        output_dir=args.output,
        base_name=args.name,
    )

    # Print output paths on stdout (for skill integration)
    for p in saved:
        print(p)


if __name__ == "__main__":
    main()
