"""
Option 2: SDXL-Turbo + nerijs/pixel-art-xl LoRA.

The LoRA steers the model toward pixel art style sprites.
Trying lora_scale 0.8 and 1.2 to see how strongly it pulls.
Each of 3 frames is generated independently (no img2img conditioning),
so this tests whether the LoRA alone is enough for sprite coherence.
"""

import sys
import torch
from pathlib import Path
from diffusers import AutoPipelineForText2Image

DEVICE = "mps"
DTYPE  = torch.float16
OUTPUT = Path("test-output/lora")
OUTPUT.mkdir(parents=True, exist_ok=True)

PROMPT_BASE = (
    "pixel art rabbit sprite moving right, side view, "
    "single character, game sprite, flat colors, crisp pixel edges, "
    "isolated on white background"
)
NEGATIVE = (
    "multiple rabbits, sprite sheet, photorealistic, 3D, blurry, "
    "text, watermark, busy background, smooth gradients"
)

FRAME_HINTS = [
    "idle standing pose",
    "mid-stride running pose, one leg forward",
    "full sprint, both feet off ground",
]

print("Loading SDXL-Turbo …", file=sys.stderr)
pipe = AutoPipelineForText2Image.from_pretrained(
    "stabilityai/sdxl-turbo",
    torch_dtype=DTYPE,
    variant="fp16",
).to(DEVICE)

print("Loading pixel-art-xl LoRA …", file=sys.stderr)
pipe.load_lora_weights(
    "nerijs/pixel-art-xl",
    weight_name="pixel-art-xl.safetensors",
)

for lora_scale in [0.8, 1.2]:
    pipe.set_adapters("default_0", adapter_weights=lora_scale)
    for i, hint in enumerate(FRAME_HINTS):
        prompt = f"{PROMPT_BASE}, {hint}, pixel_art"  # trigger token for this LoRA
        tag = f"f{i+1}_scale{int(lora_scale*10)}"
        print(f"\nGenerating frame {i+1} (lora_scale={lora_scale}) …\n  {prompt}", file=sys.stderr)

        result = pipe(
            prompt=prompt,
            negative_prompt=NEGATIVE,
            num_inference_steps=4,
            guidance_scale=0.0,
            width=512, height=512,
        )
        path = OUTPUT / f"rabbit_{tag}.png"
        result.images[0].save(path)
        print(f"Saved {path}", file=sys.stderr)

print("\nDone. Files in", OUTPUT, file=sys.stderr)
