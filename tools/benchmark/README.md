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

A local model entry can select the connector and an independent concurrency
group:

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
  --workers 20 \
  --provider-workers provider-a=10 \
  --provider-workers provider-b=10 \
  --runner python \
  --action-timeout 1800
```

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
  --workers 2 \
  --provider-workers provider-a=1 \
  --provider-workers provider-b=1 \
  --runner python \
  --action-timeout 1800 \
  --run-dir tools/benchmark/results/run/CANARY_DIRECTORY
```
