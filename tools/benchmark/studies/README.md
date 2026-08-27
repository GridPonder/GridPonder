# Manifest-defined studies

`run_queue.py` remains the launcher for the legacy 11-configuration benchmark.
`run_study.py` runs the predeclared nested-panel design used by the final paper.

Start from `final-study.template.yaml`, replace the example games and model
variants, and save the frozen manifest outside Git or under a `.local.yaml`
name. Validate and inspect the exact deduplicated workload before model calls:

```bash
python tools/benchmark/run_study.py \
  --manifest tools/benchmark/studies/final-study.local.yaml \
  --packs-dir /path/to/frozen/packs \
  --validate-only

python tools/benchmark/run_study.py \
  --manifest tools/benchmark/studies/final-study.local.yaml \
  --packs-dir /path/to/frozen/packs \
  --dry-run
```

The final run should use a clean public engine commit, a clean private-pack
commit, a new result directory, and explicit per-model worker limits.
