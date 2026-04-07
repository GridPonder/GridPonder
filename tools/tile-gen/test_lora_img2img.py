"""
Option 3: LoRA (pixel art style) + img2img (frame coherence).

Frame 1: text2img with LoRA active → single clean pixel art sprite.
Frames 2+: img2img conditioned on frame 1, with LoRA still active →
           same character, different pose.

Testing strength values 0.5 and 0.65.
"""

import sys
import torch
from pathlib import Path
from diffusers import AutoPipelineForText2Image, AutoPipelineForImage2Image
from PIL import Image

DEVICE = "mps"
DTYPE  = torch.float16
OUTPUT = Path("test-output/lora-img2img")
OUTPUT.mkdir(parents=True, exist_ok=True)

LORA_SCALE = 0.9  # strong enough for pixel art, not so strong it fights img2img

PROMPT_BASE = (
    "pixel_art, single rabbit game sprite, side view facing right, "
    "pixel art, 16-bit style, flat colors, crisp pixel edges, "
    "isolated on white background, no background, single character only"
)
NEGATIVE = (
    "multiple characters, sprite sheet, multiple poses, photorealistic, 3D, "
    "blurry, smooth gradients, text, watermark, accessories, backpack, collar"
)

FRAME_HINTS = [
    "standing idle pose, both feet on ground",
    "mid-stride running, right leg forward, left leg back",
    "full leap, both feet off ground, body horizontal",
]

# ---------------------------------------------------------------------------
print("Loading text2img pipeline …", file=sys.stderr)
txt2img = AutoPipelineForText2Image.from_pretrained(
    "stabilityai/sdxl-turbo",
    torch_dtype=DTYPE,
    variant="fp16",
).to(DEVICE)

print("Loading pixel-art-xl LoRA …", file=sys.stderr)
txt2img.load_lora_weights(
    "nerijs/pixel-art-xl",
    weight_name="pixel-art-xl.safetensors",
)
txt2img.set_adapters("default_0", adapter_weights=LORA_SCALE)

print("Creating img2img pipeline from same weights …", file=sys.stderr)
img2img = AutoPipelineForImage2Image.from_pipe(txt2img)

# ---------------------------------------------------------------------------
# Frame 1: text2img
# ---------------------------------------------------------------------------
prompt_f1 = f"{PROMPT_BASE}, {FRAME_HINTS[0]}"
print(f"\nGenerating frame 1 (text2img + LoRA) …\n  {prompt_f1}", file=sys.stderr)

f1_result = txt2img(
    prompt=prompt_f1,
    negative_prompt=NEGATIVE,
    num_inference_steps=4,
    guidance_scale=0.0,
    width=512, height=512,
)
frame1: Image.Image = f1_result.images[0]
frame1.save(OUTPUT / "rabbit_f1.png")
print("Saved frame 1", file=sys.stderr)

# ---------------------------------------------------------------------------
# Frames 2 & 3: img2img conditioned on frame 1, at two strength levels
# ---------------------------------------------------------------------------
for strength in [0.5, 0.65]:
    stag = f"str{int(strength * 100)}"
    for fi, hint in enumerate(FRAME_HINTS[1:], start=2):
        prompt = f"{PROMPT_BASE}, {hint}"
        print(f"\nGenerating frame {fi} (img2img strength={strength}) …\n  {prompt}", file=sys.stderr)

        result = img2img(
            prompt=prompt,
            negative_prompt=NEGATIVE,
            image=frame1,
            strength=strength,
            num_inference_steps=4,
            guidance_scale=0.0,
        )
        path = OUTPUT / f"rabbit_f{fi}_{stag}.png"
        result.images[0].save(path)
        print(f"Saved {path}", file=sys.stderr)

print("\nDone. Files in", OUTPUT, file=sys.stderr)
