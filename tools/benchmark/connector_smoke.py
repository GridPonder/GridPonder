#!/usr/bin/env python3
"""Run small text/image and concurrency checks through configured connectors."""
from __future__ import annotations

import argparse
import base64
import io
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent_client import call_llm
from bench import expand_model_variants, load_models
from connector_api import estimate_cost


def _test_image() -> str:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (96, 96), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 43, 43), fill="#dc2626")
    draw.rectangle((52, 52, 87, 87), fill="#2563eb")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--image", action="store_true")
    args = parser.parse_args()

    variants = expand_model_variants(load_models(), args.model)
    if len(variants) != len(args.model):
        raise SystemExit("One or more requested model variants were not found")
    image_b64 = _test_image() if args.image else None
    prompt = (
        'Return exactly {"action":"move","direction":"right"}.'
        if not args.image
        else 'The image contains two colored squares. Return exactly '
        '{"action":"move","direction":"right"}.'
    )

    jobs = [
        (model, variant, index)
        for model, variant in variants
        for index in range(args.parallel)
    ]

    def execute(job):
        model, variant, index = job
        target = model.get("model") or model.get("litellm_model")
        result = call_llm(
            prompt,
            target,
            variant.get("params") or {},
            max_tokens=128,
            request_timeout=args.timeout,
            image_b64=image_b64,
            connector=model.get("connector", "litellm"),
        )
        return model, variant, index, result

    failures = 0
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        futures = [executor.submit(execute, job) for job in jobs]
        for future in as_completed(futures):
            try:
                model, variant, index, result = future.result()
                text, latency, in_tok, reason_tok, out_tok, cost, _ = result
                if cost is None:
                    cost = estimate_cost(
                        in_tok,
                        out_tok,
                        model.get("pricing"),
                    )
                full_id = model["id"] + variant.get("suffix", "")
                ok = '"action"' in text and '"right"' in text
                failures += int(not ok)
                print(
                    f"{'PASS' if ok else 'FAIL'} {full_id}[{index}] "
                    f"{latency / 1000:.1f}s in={in_tok} reasoning={reason_tok} "
                    f"out={out_tok} cost="
                    f"{f'${cost:.4f}' if cost is not None else 'n/a'} "
                    f"response={text!r}"
                )
            except Exception as exc:
                failures += 1
                print(f"FAIL {type(exc).__name__}: {exc}")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
