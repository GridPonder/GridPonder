# Agent harness

Runs GridPonder levels as sandboxed agent sessions. The agent gets a directory,
a generated `RULES.md`, and a `./play` command. It never sees the pack, the gold
path, the action limit, or the list of currently legal moves — and under the
default confinement those files do not exist for it at all.

```
sweep.py          many levels, one agent, concurrency, repeats
  └── supervisor.py     one level, one session          sandbox/
        ├── loads the pack                              ├── RULES.md   generated per level
        ├── binds the socket                            ├── play       stdlib-only client
        ├── spawns runner.py --observation harness      └── .play.sock bound by the supervisor
        └── launches the agent under bwrap
report.py         results.json -> PDF
```

## A full run

```bash
PACKS=../gridponder-private

# play 10 levels, 2 attempts each, confined
python tools/benchmark/harness/sweep.py \
    --packs-dir $PACKS --out tmp/run \
    --agent claude --model haiku

# turn the results into a PDF
python tools/benchmark/harness/report.py tmp/run/results.json -o tmp/run/report.pdf
```

`--agent baseline` swaps in a local random player that costs nothing. It solves
almost nothing, but it produces losses, retries and rejections on demand, which
is what you want when checking the pipeline rather than a model.

One level on its own:

```bash
python tools/benchmark/harness/supervisor.py \
    --pack three_kingdoms --level tk_001 --packs-dir $PACKS \
    --sandbox tmp/sbx --result tmp/sbx.json \
    --agent claude --model haiku --max-attempts 3
```

Drop `--agent` to leave the sandbox open and play it yourself.

## Confinement

`--isolation bwrap` (the default) builds a root filesystem from read-only system
paths plus the sandbox directory. The repo, the packs and the solver are not
mounted, so reading them fails with ENOENT rather than being merely discouraged.
Network stays shared, because a hosted model is unreachable without it.

Before each scored session the supervisor checks the confinement against the
pack it is about to score, and refuses to run if that path is reachable. One
stray `--ro-bind` would otherwise re-expose the gold path and quietly invalidate
every number downstream.

`--isolation none` runs the agent with your own filesystem view. It exists for
debugging local agents whose scripts live in this repo. Any score produced that
way is unverified, and the PDF says so on its first page.

## What the agent can do

Four verbs, and nothing else is accepted:

    ./play state          print the board, the goal, and the action counts
    ./play move '<json>'  submit one action
    ./play history        list the actions taken this attempt
    ./play give_up        restart the attempt from the initial board

`./play` exits 0 normally, 3 once the run is over, 2 on a transport failure.

## Attempts and losses

With `run.max_attempts > 1`, losing resets the board and costs an attempt
instead of ending the run, so a result can say "solved on attempt 3 after two
losses" rather than only "failed".

`run.full_attempts` decides what one of those attempts is worth:

- **true** — every attempt gets the budget the level itself declares (its
  `max_actions` lose condition), and the run's total is the sum.
- **false** — one budget of `total_multiplier × gold path`, shared by all
  attempts.

The shared form quietly makes late attempts unwinnable. On `tk_008` the gold
path is 18 and the level's own cap is 21, so three shared attempts are worth
54 actions: the first two consume 42 and the third starts with 12 — fewer than
a *perfect* solve needs. An agent that loses twice is then scored on an attempt
it could not have won, which measures budget arithmetic rather than the puzzle.
With `full_attempts` the same run is worth 3 × 21 = 63 and each attempt is a
real second chance.

At `max_attempts: 1` a loss ends the run, which is the historical behaviour and
still what `bench.py` gets.

## Rejections come in two kinds

They mean opposite things, are counted separately, and have separate limits:

- **schema** — the JSON did not name a real action or did not match that
  action's declared parameters. The agent could not say what it meant. This is
  friction: a docs or level defect. Five in a row end the run.
- **illegal** — a well-formed action the engine refused in this position.
  Ordinary probing, and never classifies a run. It takes 25 in a row to stop a
  run, purely as a loop guard.

Sharing one limit between them was a real bug: on a pack that makes you select a
piece before moving it, hunting for the selectable cell produced five illegal
moves immediately and ended the run at zero actions.

Neither kind costs an action. An action the engine *accepts* but that does
nothing (walking into a wall under `avatar_navigation`, tapping under
`coupled_actors`) is a real turn and shows up as inefficiency — see "Known gaps".

## Anonymous runs

`--anon` hides the semantics an agent could otherwise recall from the world:
entity kinds become letters, action ids become `a1, a2, …`, parameter names
`p1, p2, …`, and enumerated values `v1, v2, …`.

That aliasing is built from `game.json` alone, so it is stable for the whole run
and is published in `RULES.md`. This is deliberately *not*
`build_anon_reverse_map`, whose labels enumerate the legal moves in the current
state — publishing those would replace search with menu-filtering, which is the
one thing this harness exists to prevent.

## Reading a run afterwards

`sweep.py` writes a transcript per session under `transcripts/`, and the
supervisor takes `--transcript` directly. Two files per session:

    <tag>.jsonl              every ./play call: verb, args, reply, timing,
                             attempt, and what that call cost in rejections
    <tag>.agent.jsonl        the agent's own message stream, raw

That pairing is what lets the report say *where* a run went wrong rather than
only that it did. `timeline.py` turns the two into per-attempt totals, an
ordered list of obstacles — each rejection and each lost attempt, with the
reasoning the agent gave just before it — the turns it thought longest about,
and a merged `dialogue`: reasoning, the command it produced, and the reply it
got, in order. Both halves, because an agent trips where its expectation and
the board come apart, and those live in different files. The claude adapter
runs with `--output-format stream-json` for this reason; the single-object form
reports only a final tally.

The agent's stream is written to disk as it arrives, not handed over when the
process exits — a run that hits the timeout is usually the long, hard one whose
transcript is worth the most.

### Getting the agent to say more

**Scraping the model's output does not work.** Claude Code's headless stream
emits thinking blocks with their content stripped — `{"type": "thinking",
"thinking": "", "signature": "…"}` — with or without
`--include-partial-messages`. Across two real `tk_008` runs that was 41
thinking blocks and 0 characters between them. Whatever the model does not
write as plain text simply never reaches disk, and how much it writes is its
own choice: 27 of 62 commands on the first run, 0 of 7 on the next.

Two things follow.

`run.thinking_tokens` is off by default because it makes this *worse*. Forcing
a budget moves reasoning into the blocks that get stripped and takes the
plain-text narration with it — the same level produced 28 text blocks and 2,349
characters without it, and 0 of each with it. The knob remains because a larger
budget is a real property of a run, just not a readable one.

`run.narrate` puts the reasoning in the protocol instead. `./play move` takes
an optional second argument — one line saying why — which is recorded against
that move in the transcript. It cannot be redacted, it is attached to the move
rather than aligned with it by position, and because it is documented in
`RULES.md` it reaches every adapter rather than only the one whose launch
prompt we control. Asking in the prompt was tried first and produced nothing.

`coverage` in the timeline reports what fraction of commands arrived with their
own reasoning, so a reader knows how much of a run is explained rather than
assuming all of it. A reason the agent stated wins over one scraped from the
stream, and is marked `stated` in the appendix.

Two honesty rules. Narration asks the agent for work on every move, so it is
recorded on the run and a narrated run is not directly comparable with a silent
one. And a move made without any reason inherits the previous one's quote for
context but is marked `reasoning_fresh: false` — an unlabelled quote would
attribute a reason to a decision the agent never explained, and those silent
moves are exactly what a reader is hunting for.

`--trace` additionally prints one line per move to stderr while the run is in
flight, since a hosted model can think for minutes and a silent supervisor is
indistinguishable from a hung one.

## The report

`report.py` writes a PDF and, unless `--no-html`, a self-contained HTML twin
beside it. It renders a summary, a per-level chart, a table, and one section per
session with a transcript. It keeps
solved / losses / efficiency / friction as separate columns on purpose: a level
nobody solves is hard, but a level nobody solves *and* everyone racks up schema
rejections on is badly documented, and collapsing the two is how a benchmark
ends up measuring its own rules text.

Efficiency is averaged over solved runs only. Including failures would fold in
runs that stopped at the action budget and make an unsolved level look cheap.

**Token cost is not spend.** The agent CLI derives it from its own token counts
at published API prices — the figure reproduces to the cent from `usage`, cache
reads and all. A run on a subscription login is metered against rate limits and
bills nothing, so the number is a forecast of what a sweep would cost on an API
key, and a sound basis for comparing runs, but never a receipt. It is labelled
"Token cost (list price)" for that reason.

## Known gaps

- `RULES.md` lists every action in `game.json`, including ones no enabled system
  handles on that level. On a `coupled_actors` level a documented `tap_cell` is
  accepted as a no-op and silently costs a turn. Fixing this properly needs the
  DSL to say which system owns an action.
- `render_goals` has no `balance` branch, so an anonymous `three_kingdoms` run
  is told its goal is the literal word `balance`. Anonymous sweeps of that pack
  are not meaningful until that is written.
- `harness.yaml`'s `tier2` block is still unread; only `thresholds`, `run` and
  the swept tier are used.
- The Dart runner has no `--observation harness`; harness mode is Python-only.

## Tests

```bash
GRIDPONDER_PRIVATE_PACKS=../gridponder-private \
    python -m pytest tools/benchmark/harness/tests
```

The end-to-end tests drive real subprocesses over a real socket, and the
isolation tests assert the negative directly — that the pack is unreadable from
inside the confinement. Both need the private packs and skip without them.

Tests also skip a level whose `max_actions` is lower than its own gold path:
such a level cannot be won by anyone, and that is a level defect rather than a
harness failure. `engines/python/test_gold_paths.py` does not catch those, since
it replays the whole path and checks `is_won` at the end without ever checking
`is_lost` along the way.
