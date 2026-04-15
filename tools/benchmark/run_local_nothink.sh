#!/usr/bin/env bash
# Run the curated suite for all local non-thinking models (Gemma 4 + Qwen 3.5)
# across every combination of inference mode (single / flex-n / full) and
# anonymisation (normal / anon) — 5 runs in total.
# full+anon is intentionally skipped: without intermediate feedback and without
# semantic labels, every model scores near-zero, producing no useful signal.
#
# Usage: cd tools/benchmark && bash run_local_nothink.sh
#
# Note: archive results/run/ before re-running if any curated-suite levels
# have changed since the last run, to avoid mixing stale and fresh results.

set -euo pipefail

MODELS=(
  --model gemma4-e2b
  --model gemma4-e4b
  --model qwen3.5-0.8b
  --model qwen3.5-2b
  --model qwen3.5-4b
  --model qwen3.5-9b
)

for mode in single flex-n full; do
  for anon_flag in "" "--anon"; do
    # full+anon produces near-zero signal for all models — skip it.
    [ "$mode" = "full" ] && [ "$anon_flag" = "--anon" ] && continue

    label="${mode}${anon_flag:+ anon}"
    echo ""
    echo "=== Running: $label ==="
    python bench.py --suite curated --mode "$mode" "${MODELS[@]}" $anon_flag
  done
done

echo ""
echo "=== All 5 combinations done. Run: python aggregate.py ==="
