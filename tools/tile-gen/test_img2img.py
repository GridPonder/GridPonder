"""
Option 1: img2img conditioning for animation frames.

Frame 1 is generated with text2img. Frames 2+ are generated with
img2img using frame 1 as the init image, so the character shape and
colour are constrained by the reference.

Trying strength values 0.5 and 0.7:
  - 0.5 → very similar to frame 1, less pose variation
  - 0.7 → more variation, riskier consistency
"""

import sys
import torch
from pathlib import Path
from diffusers import AutoPipelineForText2Image, AutoPipelineForImage2Image
from PIL import Image

DEVICE = "mps"
DTYPE  = torch.float16
OUTPUT = Path("test-output/img2img")
OUTPUT.mkdir(parents=True, exist_ok=True)

PROMPT_BASE = (
    "single cartoon rabbit character moving right, side view, "
    "2D cartoon game sprite, flat colors, bold clean black outlines, "
    "isolated on plain white background, simple and clear, no background details"
)
NEGATIVE = (
    "multiple rabbits, sprite sheet, comic strip, photorealistic, 3D, "
    "blurry, text, watermark, busy background, shadow"
)

FRAME_HINTS = [
    "standing upright, weight on both feet, idle pose",
    "mid-stride, one leg forward, arms out, running pose",
    "leaning forward, both feet off ground, full sprint",
]

print("Loading text2img pipeline …", file=sys.stderr)
txt2img = AutoPipelineForText2Image.from_pretrained(
    "stabilityai/sdxl-turbo",
    torch_dtype=DTYPE,
    variant="fp16",
).to(DEVICE)

print("Loading img2img pipeline from same weights …", file=sys.stderr)
img2img = AutoPipelineForImage2Image.from_pipe(txt2img)

# --- Generate frame 1 (reference) ---
prompt_f1 = f"{PROMPT_BASE}, {FRAME_HINTS[0]}"
print(f"Generating frame 1 …\n  {prompt_f1}", file=sys.stderr)
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

# --- Frames 2 & 3 via img2img at two strength levels ---
for frame_idx in [1, 2]:
    for strength in [0.5, 0.7]:
        hint  = FRAME_HINTS[frame_idx]
        prompt = f"{PROMPT_BASE}, {hint}"
        tag   = f"f{frame_idx+1}_str{int(strength*10)}"
        print(f"\nGenerating frame {frame_idx+1} (strength={strength}) …\n  {prompt}", file=sys.stderr)

        result = img2img(
            prompt=prompt,
            negative_prompt=NEGATIVE,
            image=frame1,
            strength=strength,
            num_inference_steps=4,
            guidance_scale=0.0,
        )
        img = result.images[0]
        path = OUTPUT / f"rabbit_{tag}.png"
        img.save(path)
        print(f"Saved {path}", file=sys.stderr)

print("\nDone. Files in", OUTPUT, file=sys.stderr)
