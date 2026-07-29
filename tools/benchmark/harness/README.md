# Agent harness

Runs one GridPonder level as a sandboxed agent session: the agent gets a
directory, a generated `RULES.md`, and a `./play` command. It never sees the
pack, the gold path, the action limit, or the list of currently legal moves.

```
supervisor.py                        sandbox/
├── loads the pack                   ├── RULES.md   generated per level
├── spawns runner.py                 ├── play       stdlib-only client
│   --observation harness            └── .play.sock bound by the supervisor
├── binds .play.sock
└── launches the agent (cwd=sandbox)
```

## Running one level

```bash
python tools/benchmark/harness/supervisor.py \
    --pack three_kingdoms --level tk_001 \
    --packs-dir ../gridponder-private \
    --sandbox tmp/sbx --result tmp/sbx.json \
    --agent-cmd claude -p "Read RULES.md and solve the puzzle."
```

Drop `--agent-cmd` to leave the sandbox open and play it yourself. Add `--anon`
for an anonymous run (see below). The result JSON carries the run's counters and
its tier.

## What the agent can do

Four verbs, and nothing else is accepted:

    ./play state          print the board, the goal, and the action counts
    ./play move '<json>'  submit one action
    ./play history        list the actions taken this attempt
    ./play give_up        restart the attempt from the initial board

`./play` exits 0 normally, 3 once the run is over, 2 on a transport failure.

## Rejections come in two kinds

They mean opposite things and are counted separately:

- **schema** — the JSON did not name a real action or did not match that
  action's declared parameters. The agent could not say what it meant. This is
  friction: a docs or level defect, and five in a row end the run.
- **illegal** — a well-formed action the engine refused in this position.
  Ordinary probing. Reported, but it never classifies a run.

Neither costs an action. Note that an action the engine *accepts* but that does
nothing (walking into a wall under `avatar_navigation`, tapping under
`coupled_actors`) is a real turn and shows up as inefficiency, not as a
rejection — see "Known gaps".

## Anonymous runs

`--anon` hides the semantics an agent could otherwise recall from the world:
entity kinds become letters, action ids become `a1, a2, …`, parameter names
`p1, p2, …`, and enumerated values `v1, v2, …`.

That aliasing is built from `game.json` alone, so it is stable for the whole run
and is published in `RULES.md`. This is deliberately *not*
`build_anon_reverse_map`, whose labels enumerate the legal moves in the current
state — publishing those would replace search with menu-filtering, which is the
one thing this harness exists to prevent.

## Scope

In: one level, one agent, one process, and the metrics for that run.

Out: sweeping levels across harnesses and models. `harness.yaml`'s `tier1`,
`tier2` and `concurrency` blocks describe that orchestrator; only `thresholds`
is read today.

## Known gaps

- `RULES.md` lists every action in `game.json`, including ones no enabled system
  handles on that level. On a `coupled_actors` level a documented `tap_cell` is
  accepted as a no-op and silently costs a turn. Fixing this properly needs the
  DSL to say which system owns an action.

## Tests

```bash
python -m pytest tools/benchmark/harness/tests
```

The end-to-end tests drive real subprocesses over a real socket. They need the
private packs, and skip without them:

```bash
GRIDPONDER_PRIVATE_PACKS=../gridponder-private \
    python -m pytest tools/benchmark/harness/tests
```
