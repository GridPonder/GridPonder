# GridPonder benchmark

Use Python 3.10 or newer. A Python 3.12 virtual environment is recommended.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r tools/benchmark/requirements.txt
.venv/bin/python tools/benchmark/preflight.py \
  --output tools/benchmark/results/preflight/public.json
```

## Model connectors

Models use LiteLLM unless their registry entry sets `connector`. Additional
connectors are machine-local modules:

```text
tools/benchmark/connectors.local/<connector>.py
```

The directory is gitignored. It can be overridden with
`GRIDPONDER_CONNECTOR_DIR`. A module exposes an object named `connector` with:

```python
def complete(request: CompletionRequest) -> CompletionResult:
    ...
```

The request and result types are defined in `connector_api.py`. The interface
supports text and inline PNG input and does not assume a particular API,
authentication scheme, or model provider.

A local model entry can select the connector and retain a concurrency group
for transport metadata:

```yaml
- id: example-frontier
  display_name: "Example Frontier"
  connector: "frontier"
  model: "example-frontier"
  concurrency_group: "provider-a"
  local: false
  pricing:
    input_per_million: 2.00
    output_per_million: 8.00
  variants:
    - suffix: "-reasoning"
      reasoning: true
      params:
        reasoning_effort: "high"
```

`models.local.yaml` is also gitignored.

`pricing` is optional. If the connector does not report monetary cost, these
per-million-token rates produce an estimate. Output token usage is assumed to
include hidden reasoning tokens, as it does for the supported flagship
transports.

## Full queue

The eleven standard configurations are generated with:

```bash
.venv/bin/python tools/benchmark/run_queue.py --all \
  --modes single flex-n full \
  --anon-modes single flex-n \
  --input-modes text image text+image \
  --model MODEL_A --model MODEL_B \
  --workers-per-model 10 \
  --runner python \
  --action-timeout 1800
```

Every resolved model variant has its own executor. Slow or rate-limited work
for one model cannot occupy another model's worker threads. Use repeatable
`--model-workers MODEL=N` arguments when individual models need different
limits.

Each active level writes an atomic snapshot under `RUN_DIRECTORY/progress/`.
Inspect action counters, model-call age and the projected time to each action
limit while a run is active:

```bash
.venv/bin/python tools/benchmark/live_status.py \
  --results-dir tools/benchmark/results/run/RUN_DIRECTORY
```

The action-limit ETA uses observed wall-clock actions per second. It is a
conservative projection for runs that may solve before exhausting their limit.
Snapshots are telemetry only: write failures are reported but do not fail a
benchmark item.

`--all` follows each pack's `levelSequence`. Level files that are not referenced
by that sequence are intentionally outside the benchmark scope.

Always run `preflight.py` first and use a new `--run-dir`. Build the internal,
self-contained report from only that run:

```bash
.venv/bin/python tools/benchmark/private_report.py \
  --results-dir tools/benchmark/results/run/RUN_DIRECTORY
```

Connector-reported cost is recorded when available. When a transport only
returns token usage, reports show cost as `n/a` rather than treating it as
zero.

Before the full queue, run the same matrix on one short level:

```bash
.venv/bin/python tools/benchmark/run_queue.py --level PACK LEVEL \
  --modes single flex-n full \
  --anon-modes single flex-n \
  --input-modes text image text+image \
  --model MODEL_A --model MODEL_B \
  --workers-per-model 1 \
  --runner python \
  --action-timeout 1800 \
  --run-dir tools/benchmark/results/run/CANARY_DIRECTORY
```

Resume normally uses the same source SHA. A reviewed descendant commit limited
to the benchmark scheduler/report or state-key normalization can resume an
existing run with:

```bash
--allow-source-migration \
--source-migration-reason "make nested engine state keys hashable"
```

The launcher rejects dirty trees, changed packs or experiment settings, and
source diffs outside the reviewed migration paths. The run metadata and private
report retain source and scheduler histories. The previous
`--allow-scheduler-migration` option remains as a compatibility alias.

## Final nested-panel study

The paper study is intentionally not a full model x configuration Cartesian
product. `run_study.py` reads one immutable manifest, expands its predeclared
panels, and deduplicates controls that are byte-compatible across panels.
Complete games remain the sampling unit.

Start from:

```text
tools/benchmark/studies/final-study.template.yaml
tools/benchmark/studies/model-selection.template.json
tools/benchmark/studies/panel-selection.template.json
```

Save frozen private copies with `.local.yaml` / `.local.json` names. They are
gitignored. The selection-record contents are included in the resolved study
digest, so changing a model decision or diagnostic panel invalidates resume.

Validate engine behavior, every observation, authored instructions, panel
scope, and workload expansion:

```bash
.venv/bin/python tools/benchmark/preflight.py \
  --packs-dir /path/to/frozen/private-packs \
  --study-manifest tools/benchmark/studies/final-study.local.yaml \
  --output tools/benchmark/results/preflight/final-study.json

.venv/bin/python tools/benchmark/run_study.py \
  --packs-dir /path/to/frozen/private-packs \
  --manifest tools/benchmark/studies/final-study.local.yaml \
  --dry-run
```

Launch from clean public-engine and private-pack commits:

```bash
.venv/bin/python tools/benchmark/run_study.py \
  --packs-dir /path/to/frozen/private-packs \
  --manifest tools/benchmark/studies/final-study.local.yaml \
  --run-dir /path/to/study-results \
  --workers-per-model 20 \
  --action-timeout 1800 \
  --runner python
```

Every resolved model has an independent executor. Curriculum sessions are
ordered within model x configuration x game, while different sessions remain
parallel. Gameplay is atomically checkpointed before the short notebook
reflection call. A reflection failure therefore resumes from reflection rather
than repeating the paid gameplay episode.

The independent and curriculum conditions receive the same authored
instructions for a target level. The curriculum condition additionally receives
a bounded cross-level notebook derived from earlier gameplay. Anonymous cells
continue to use the legacy anonymised prompt and never receive semantic stories
or notebooks.

Inspect live action counters with `live_status.py`. Generate the matched study
analysis and optional website data with:

```bash
.venv/bin/python tools/benchmark/study_report.py \
  --results-dir /path/to/study-results \
  --output tools/benchmark/study-leaderboard.json

cd website
GRIDPONDER_STUDY_DATA=../tools/benchmark/study-leaderboard.json npm run build
```

The study page reports headline capability, planning, representation, semantic
surface, curriculum, reliability, and per-game challenge durability. Every
contrast exposes its matched denominator and scope. Curriculum confidence
intervals resample complete games.
