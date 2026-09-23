#!/usr/bin/env python3
"""Cross-runner prompt parity check: Python runner vs Dart runner.

Both benchmark runners build the LLM prompt independently (Python:
tools/benchmark/runner.py + engines/python; Dart: tools/benchmark/runner +
engines/dart/lib/src/agent). They must produce byte-identical prompts and
identical valid-action lists. This script drives both runners through every
level's gold path (named and --anon) and compares every emitted state event:
the initial state, the state after each gold action, and the terminal event.
It also reports any run whose gold path does not end in a `won` event.

Built-in scenarios (--scenarios) also drive paths gold runs never take — a
lost attempt with --max-attempts, rejected and malformed actions, an edge bump
that changes nothing, the harness action cap, fixed-n batches and the harness
observation payload — and compare every event (rejected/reset/lost included).

Diffs are attributed to prompt sections (header, goal, board, status,
last_action, commentary, actions, tail) so a known-divergent section can be
excluded with --ignore-sections while the rest is held to zero diffs.

Usage:
  python3.12 tools/benchmark/check_prompt_parity.py \\
      --packs-dir packs --packs-dir /path/to/private/packs \\
      [--python-root /path/to/other/checkout] [--pack keystone] [--level ks_001] \\
      [--modes named,anon] [--ignore-sections goal,status] [--jobs 8]

--python-root selects which checkout's runner.py (and therefore which
engines/python) is the reference; default is this repository. The Dart runner
is compiled from this repository into tmp/ unless --dart-runner is given.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CARDINALS = {"up", "down", "left", "right"}
_STATUS_RE = re.compile(
    r"^(Inventory:|Moves this attempt|Selected:|Moves left:|PREVIOUS ATTEMPT|"
    r"The board did not change)"
)
SECTIONS = (
    "header", "goal", "last_action", "board", "status", "commentary",
    "actions", "tail",
)


# ── Gold path / levels ──────────────────────────────────────────────────────

def gold_actions(level: dict) -> list[dict]:
    out = []
    for entry in (level.get("solution") or {}).get("goldPath") or []:
        if isinstance(entry, dict):
            action = {"action": entry.get("action", "move")}
            action.update({k: v for k, v in entry.items() if k != "action"})
            out.append(action)
        elif isinstance(entry, str):
            if entry in _CARDINALS:
                out.append({"action": "move", "direction": entry})
            else:
                out.append({"action": entry})
    return out


def discover_levels(packs_dirs: list[Path], pack_filter, level_filter):
    jobs = []
    for packs_dir in packs_dirs:
        for pack_dir in sorted(p for p in packs_dir.iterdir() if p.is_dir()):
            game_file = pack_dir / "game.json"
            if not game_file.is_file():
                continue
            if pack_filter and pack_dir.name not in pack_filter:
                continue
            game = json.loads(game_file.read_text())
            for entry in game.get("levelSequence") or []:
                if entry.get("type") != "level":
                    continue
                ref = entry["ref"]
                if level_filter and ref not in level_filter:
                    continue
                level_file = pack_dir / "levels" / f"{ref}.json"
                if not level_file.is_file():
                    continue
                jobs.append((packs_dir, pack_dir.name, ref,
                             json.loads(level_file.read_text())))
    return jobs


# ── Runner driving ──────────────────────────────────────────────────────────

class Runner:
    def __init__(self, cmd: list[str]):
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
        )

    def read_until_state(self) -> list[dict]:
        """Read events up to and including the next state/won/lost event."""
        events = []
        while True:
            line = self.proc.stdout.readline()
            if not line:
                err = self.proc.stderr.read()
                events.append({"event": "EOF", "stderr": err[-2000:]})
                return events
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                events.append({"event": "NONJSON", "line": line[:500]})
                continue
            events.append(event)
            if event.get("event") in ("state", "won", "lost"):
                return events

    def send(self, obj: dict) -> None:
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _anon_label(valid_actions: list[dict], action: dict) -> str | None:
    real = [a for a in valid_actions if a.get("action") != "give_up"]
    ordered = sorted(real, key=lambda a: json.dumps(a, sort_keys=True))
    want = json.dumps(action, sort_keys=True)
    for i, a in enumerate(ordered):
        if json.dumps(a, sort_keys=True) == want:
            return f"a{i + 1}"
    return None


def _submission(item, last_state: dict, anon: bool, gold: list[dict]):
    """What to write to the runner for one script item (None = skip)."""
    kind, value = item
    if kind == "raw":
        return value
    if kind == "batch":
        return {"actions": value}
    # "act": a real action; anonymous runs submit its current label, or an
    # unknown label (a schema rejection) when the action is not offered.
    if not anon:
        return value
    label = _anon_label(last_state.get("valid_actions") or [], value)
    return {"action": label or "a999"}


def drive(cmd: list[str], items: list[tuple[str, object]], anon: bool,
          stop_on_unoffered: bool = False) -> list[list[dict]]:
    """Run one level through a script; return the events of each step
    (initial, then one list per submitted item, each ending at the next
    state/won/lost event)."""
    runner = Runner(cmd)
    steps: list[list[dict]] = []
    try:
        steps.append(runner.read_until_state())
        for item in items:
            last = steps[-1][-1]
            if last.get("event") != "state":
                break
            if (stop_on_unoffered and anon and item[0] == "act"
                    and _anon_label(last.get("valid_actions") or [], item[1]) is None):
                steps.append([{"event": "GOLD_ACTION_NOT_OFFERED", "action": item[1]}])
                break
            runner.send(_submission(item, last, anon, []))
            steps.append(runner.read_until_state())
    finally:
        runner.close()
    return steps


# ── Comparison ──────────────────────────────────────────────────────────────

def section_of_lines(prompt: str) -> list[tuple[str, str]]:
    section = "header"
    out = []
    for line in prompt.split("\n"):
        if line.startswith("GOAL: "):
            section = "goal"
        elif line.startswith("LAST ACTION:"):
            section = "last_action"
        elif (line.startswith("CURRENT BOARD") or line.startswith("BOARD BEFORE:")
              or line.startswith("BOARD AFTER")):
            section = "board"
        elif line.startswith("Compare the two boards"):
            section = "commentary"
        elif line.startswith("AVAILABLE ACTIONS:"):
            section = "actions"
        elif line.startswith("Respond with"):
            section = "tail"
        tag = section
        if section in ("board", "last_action") and _STATUS_RE.match(line):
            tag = "status"
        elif section == "last_action" and not line.startswith("LAST ACTION:"):
            tag = "board"
        out.append((tag, line))
    return out


def compare_prompts(py: str, dart: str, ignore: set[str]):
    """Return {section: [diff lines]} for sections not ignored."""
    a = section_of_lines(py)
    b = section_of_lines(dart)
    diffs: dict[str, list[str]] = {}
    sm = difflib.SequenceMatcher(a=[l for _, l in a], b=[l for _, l in b],
                                 autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        for tag, line in a[i1:i2]:
            if tag not in ignore:
                diffs.setdefault(tag, []).append(f"- py  | {line}")
        for tag, line in b[j1:j2]:
            if tag not in ignore:
                diffs.setdefault(tag, []).append(f"+ dart| {line}")
    return diffs


def canon_actions(actions) -> list[str]:
    return [json.dumps(a, sort_keys=True) for a in actions or []]


_VOLATILE_KEYS = {"prompt", "valid_actions"}


def compare_steps(py_steps, dart_steps, ignore: set[str]) -> list:
    """Problems between two runs' step/event lists."""
    problems = []
    for i in range(max(len(py_steps), len(dart_steps))):
        p_events = py_steps[i] if i < len(py_steps) else [{"event": "MISSING"}]
        d_events = dart_steps[i] if i < len(dart_steps) else [{"event": "MISSING"}]
        label = f"step {i}" if i else "initial"
        p_types = [e.get("event") for e in p_events]
        d_types = [e.get("event") for e in d_events]
        if p_types != d_types:
            lines = [f"py={p_types} dart={d_types}"]
            for side, evs in (("py", p_events), ("dart", d_events)):
                for e in evs:
                    if e.get("stderr"):
                        lines.append(f"{side} stderr: {e['stderr']}")
            problems.append((label, "event", lines))
            break
        for p, d in zip(p_events, d_events):
            etype = p.get("event")
            if etype != "state":
                if "events" not in ignore:
                    pj, dj = json.dumps(p, sort_keys=True), json.dumps(d, sort_keys=True)
                    if pj != dj:
                        problems.append((label, f"{etype}_event",
                                         [f"- py  | {pj}", f"+ dart| {dj}"]))
                continue
            if "fields" not in ignore:
                pf = {k: v for k, v in p.items() if k not in _VOLATILE_KEYS}
                df = {k: v for k, v in d.items() if k not in _VOLATILE_KEYS}
                if pf != df:
                    problems.append((label, "state_fields", [
                        f"- py  | {json.dumps(pf, sort_keys=True)}",
                        f"+ dart| {json.dumps(df, sort_keys=True)}"]))
            if "valid_actions" not in ignore and "valid_actions" in p:
                pa, da = canon_actions(p.get("valid_actions")), canon_actions(d.get("valid_actions"))
                if pa != da:
                    lines = [f"- py  | {x}" for x in pa if x not in da]
                    lines += [f"+ dart| {x}" for x in da if x not in pa]
                    if not lines:
                        lines = ["(same set, different order)"]
                    problems.append((label, "valid_actions", lines))
            for key in ("prompt", "board_text", "goals"):
                if key not in p and key not in d:
                    continue
                for section, lines in compare_prompts(
                        str(p.get(key, "")), str(d.get(key, "")), ignore).items():
                    problems.append((label, section if key == "prompt" else key, lines))
    return problems


def _accepted_but_unoffered(named_steps: list[list[dict]], actions: list[dict]) -> set[int]:
    """Gold indices the named run accepted although its state did not offer
    them. An accepted action the enumerator leaves out is one it judged to
    have no effect (e.g. re-tapping the selected piece), so an anonymous run —
    which can only submit offered labels — skips it and reaches the same
    state."""
    skip: set[int] = set()
    for i, action in enumerate(actions):
        if i + 1 >= len(named_steps):
            break
        before = named_steps[i][-1]
        if before.get("event") != "state":
            break
        offered = canon_actions(before.get("valid_actions"))
        rejected = any(e.get("event") == "rejected" for e in named_steps[i + 1])
        if json.dumps(action, sort_keys=True) not in offered and not rejected:
            skip.add(i)
    return skip


def check_level(job, args, dart_cmd_base, py_cmd_base):
    packs_dir, pack, level_id, level = job
    actions = gold_actions(level)
    results = []
    skip: set[int] = set()
    for mode in args.modes:
        anon = mode == "anon"
        items = [("act", a) for i, a in enumerate(actions)
                 if not (anon and i in skip)]
        common = ["--pack", pack, "--level", level_id,
                  "--packs-dir", str(packs_dir)] + (["--anon"] if anon else [])
        py_steps = drive(py_cmd_base + common, items, anon, stop_on_unoffered=True)
        if not anon:
            skip = _accepted_but_unoffered(py_steps, actions)
        dart_steps = drive(dart_cmd_base + common, items, anon, stop_on_unoffered=True)
        problems = []
        if actions:
            for side, steps in (("py", py_steps), ("dart", dart_steps)):
                if steps[-1][-1].get("event") != "won":
                    problems.append(("final", "gold_not_won", [
                        f"{side}: gold path ended with {steps[-1][-1].get('event')!r} "
                        f"after {len(steps) - 1}/{len(items)} actions"]))
        problems += compare_steps(py_steps, dart_steps, args.ignore_sections)
        results.append((mode, len(py_steps), problems))
    return pack, level_id, results


# ── Scenarios (paths gold runs never take) ──────────────────────────────────
#
# Each item: ("gold", n) plays the first n gold actions, ("act", action)
# submits a real action (its label in anon mode, or an unknown label when it
# is not offered), ("raw", payload) submits the payload as-is in both modes,
# ("batch", [actions]) submits a multi-action payload. `expect` lists
# substrings that must occur in the Python run's output (prompts and events),
# so a scenario proves it exercised the path it is named after; `absent` lists
# substrings that must not occur.
SCENARIOS = [
    {
        "name": "loss with a second attempt, then a final loss",
        "pack": "keystone", "level": "ks_013", "args": ["--max-attempts", "2"],
        "items": [("gold", 1), ("act", {"action": "cut", "position": [2, 1]}),
                  ("gold", 1), ("act", {"action": "cut", "position": [2, 1]})],
        "expect": {"named": ["PREVIOUS ATTEMPT: lost — Cargo was lost", '"loss_reason": "Cargo was lost'],
                   "anon": ['PREVIOUS ATTEMPT: lost — loss condition \\"#3\\" reached',
                            '"loss_reason": "loss condition \\"#3\\" reached"']},
    },
    {
        "name": "full attempts: per-attempt budget is the level's own cap",
        "pack": "keystone", "level": "ks_013",
        "args": ["--max-attempts", "2", "--full-attempts"],
        "items": [("gold", 1), ("act", {"action": "cut", "position": [2, 1]}), ("gold", 2)],
        "expect": {"named": ['"action_limit": 48', '"action_limit_per_attempt": 24']},
    },
    {
        "name": "rejected press after gold step 7, then recovery",
        "pack": "liftprint", "level": "lp_011", "args": [],
        "items": [("gold", 7), ("act", {"action": "press"}),
                  ("act", {"action": "move", "direction": "up"})],
        "expect": {"named": ["REJECTED (plate yellow at (1,1) refuses ink blue); no action was spent"],
                   "anon": ["REJECTED (unknown action label 'a999')"]},
    },
    {
        "name": "harness rejection carries the engine veto reason",
        "pack": "liftprint", "level": "lp_011",
        "args": ["--observation", "harness"],
        "items": [("gold", 7), ("raw", {"action": "press"})],
        "modes": ["named"],
        "expect": {"named": ['"detail": "plate yellow at (1,1) refuses ink blue"']},
    },
    {
        "name": "selecting a piece is a change; re-tapping it is not offered",
        "pack": "pincer", "level": "pc_001", "args": [],
        "items": [("gold", 1), ("gold", 1)],
        "expect": {"named": ["Selected: "]},
        "absent": {"named": ["The board did not change."]},
    },
    {
        "name": "a held slow train still offers wait",
        "pack": "escapement", "level": "esc_022", "args": [],
        "items": [("gold", 6), ("act", {"action": "wait"})],
        "expect": {"named": ['{"action": "wait"}']},
        "absent": {"anon": ["unknown action label"]},
    },
    {
        "name": "move before any piece is selected",
        "pack": "three_kingdoms", "level": "tk_003", "args": [],
        "items": [("act", {"action": "move", "direction": "right"}),
                  ("act", {"action": "tap_cell", "position": [1, 1]}),
                  ("act", {"action": "move", "direction": "right"})],
        "expect": {"named": ["REJECTED (move is not legal in this state)",
                             "Selected: Wei at (2,1)"],
                   "anon": ["REJECTED (unknown action label"]},
    },
    {
        "name": "balance connectivity in the goal line",
        "pack": "three_kingdoms", "level": "tk_022", "args": [],
        "items": [("gold", 3)],
        "expect": {"named": ["connected"], "anon": ["must connect orthogonally"]},
    },
    {
        "name": "edge bump that changes nothing, schema errors, give-up",
        "pack": "carrot_quest", "level": "fw_001", "args": [],
        "items": [("raw", {"action": "move", "direction": "up"}),
                  ("raw", {"action": "move", "direction": "diagonal"}),
                  ("raw", {"action": 5}),
                  ("raw", {"action": "give_up"})],
        "expect": {"named": ["The board did not change.", "must be one of",
                             "PREVIOUS ATTEMPT: given up"],
                   "anon": ["PREVIOUS ATTEMPT: given up"]},
    },
    {
        "name": "harness action cap ends an attempt",
        "pack": "carrot_quest", "level": "fw_001",
        "args": ["--attempt-multiplier", "1", "--max-attempts", "3"],
        "items": [("raw", {"action": "move", "direction": "up"})] * 6
                 + [("gold", 2)],
        "expect": {"named": ["PREVIOUS ATTEMPT: ended — harness action cap reached"]},
    },
    {
        "name": "fixed-n batches",
        "pack": "keystone", "level": "ks_001",
        "args": ["--mode", "fixed-n", "--step-size", "3"],
        "items": [("batchgold", 3), ("batchgold", 3), ("batchgold", 3)],
        "modes": ["named"],
        "expect": {"named": ["up to 3 actions"]},
    },
    {
        "name": "harness observation payload",
        "pack": "keystone", "level": "ks_001",
        "args": ["--observation", "harness"],
        "items": [("raw", {"action": "give_up"})],
        "expect": {"named": ["board_text"]},
    },
]


def _expand_items(items, gold: list[dict]):
    """Resolve ("gold", n) / ("batchgold", n) against the level's gold path."""
    out, cursor = [], 0
    for kind, value in items:
        if kind == "gold":
            out += [("act", a) for a in gold[cursor:cursor + value]]
            cursor += value
        elif kind == "batchgold":
            out.append(("batch", gold[cursor:cursor + value]))
            cursor += value
        else:
            out.append((kind, value))
    return out


def run_scenarios(args, packs_dirs, dart_cmd, py_cmd):
    total, failed = 0, 0
    for sc in SCENARIOS:
        pack_root = next((d for d in packs_dirs if (d / sc["pack"] / "game.json").is_file()), None)
        if pack_root is None:
            print(f"--- SKIP scenario {sc['name']!r}: pack {sc['pack']} not found")
            continue
        level = json.loads((pack_root / sc["pack"] / "levels" / f"{sc['level']}.json").read_text())
        items = _expand_items(sc["items"], gold_actions(level))
        for mode in sc.get("modes", args.modes):
            anon = mode == "anon"
            common = (["--pack", sc["pack"], "--level", sc["level"],
                       "--packs-dir", str(pack_root)] + sc["args"]
                      + (["--anon"] if anon else []))
            py_steps = drive(py_cmd + common, items, anon)
            dart_steps = drive(dart_cmd + common, items, anon)
            problems = compare_steps(py_steps, dart_steps, args.ignore_sections)
            blob = json.dumps(py_steps, ensure_ascii=False)
            for needle in sc.get("expect", {}).get(mode, []):
                if needle not in blob:
                    problems.append(("scenario", "expectation", [f"python output lacks {needle!r}"]))
            for needle in sc.get("absent", {}).get(mode, []):
                if needle in blob:
                    problems.append(("scenario", "expectation", [f"python output has {needle!r}"]))
            n_events = sum(len(s) for s in py_steps)
            total += 1
            status = "ok" if not problems else f"{len(problems)} problem(s)"
            print(f"--- scenario {sc['pack']}/{sc['level']} [{mode}] {sc['name']}: "
                  f"{n_events} events, {status}")
            if problems:
                failed += 1
                for label, section, lines in problems[: args.max_problems]:
                    print(f"  [{label}] {section}:")
                    for line in lines[: args.max_lines]:
                        print(f"      {line}")
    return total, failed


def build_dart_runner(out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = out_dir / "gp_runner"
    runner_dir = _REPO_ROOT / "tools" / "benchmark" / "runner"
    subprocess.run(["dart", "pub", "get"], cwd=runner_dir, check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run(["dart", "compile", "exe", "bin/runner.dart", "-o", str(exe)],
                   cwd=runner_dir, check=True, stdout=subprocess.DEVNULL)
    return [str(exe)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--packs-dir", action="append", default=None,
                    help="Directory of packs (repeatable). Default: <repo>/packs")
    ap.add_argument("--python-root", default=str(_REPO_ROOT),
                    help="Checkout whose tools/benchmark/runner.py is the reference")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--dart-runner", default=None,
                    help="Path to a compiled Dart runner (default: compile one into tmp/)")
    ap.add_argument("--pack", action="append", default=None)
    ap.add_argument("--level", action="append", default=None)
    ap.add_argument("--modes", default="named,anon")
    ap.add_argument("--ignore-sections", default="",
                    help=f"Comma list of sections to skip: {', '.join(SECTIONS)}, valid_actions")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--max-lines", type=int, default=12,
                    help="Diff lines shown per problem")
    ap.add_argument("--max-problems", type=int, default=3,
                    help="Problems shown per level/mode (all are counted)")
    ap.add_argument("--scenarios", choices=["yes", "no", "only"], default="yes",
                    help="Also run the built-in loss/rejection/limit scenarios")
    args = ap.parse_args()
    args.modes = [m for m in args.modes.split(",") if m]
    args.ignore_sections = {s for s in args.ignore_sections.split(",") if s}

    packs_dirs = [Path(p).resolve() for p in (args.packs_dir or [_REPO_ROOT / "packs"])]
    py_cmd = [args.python, str(Path(args.python_root) / "tools" / "benchmark" / "runner.py")]
    dart_cmd = ([args.dart_runner] if args.dart_runner
                else build_dart_runner(_REPO_ROOT / "tmp" / "prompt_parity"))

    scenario_total = scenario_failed = 0
    if args.scenarios != "no":
        scenario_total, scenario_failed = run_scenarios(args, packs_dirs, dart_cmd, py_cmd)
        print(f"Scenarios: {scenario_total} runs, {scenario_failed} with problems")
        if args.scenarios == "only":
            return 1 if scenario_failed else 0

    jobs = discover_levels(packs_dirs, set(args.pack or []), set(args.level or []))
    if not jobs:
        print("No levels found.")
        return 2

    totals = {"levels": 0, "runs": 0, "steps": 0, "clean_runs": 0}
    by_section: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(check_level, job, args, dart_cmd, py_cmd) for job in jobs]
        for fut in futures:
            pack, level_id, results = fut.result()
            totals["levels"] += 1
            for mode, n_steps, problems in results:
                totals["runs"] += 1
                totals["steps"] += n_steps
                if not problems:
                    totals["clean_runs"] += 1
                    continue
                for _, section, _ in problems:
                    by_section[section] = by_section.get(section, 0) + 1
                print(f"=== {pack}/{level_id} [{mode}] — {len(problems)} problem(s)")
                for label, section, lines in problems[: args.max_problems]:
                    print(f"  [{label}] {section}:")
                    for line in lines[: args.max_lines]:
                        print(f"      {line}")
                    if len(lines) > args.max_lines:
                        print(f"      ... {len(lines) - args.max_lines} more")

    print()
    print(f"Levels: {totals['levels']}  runs: {totals['runs']}  "
          f"state events compared: {totals['steps']}  clean runs: {totals['clean_runs']}")
    if scenario_total:
        print(f"Scenarios: {scenario_total} runs, {scenario_failed} with problems")
    if by_section or scenario_failed:
        print("Problems by section (step-level count): "
              + ", ".join(f"{k}={v}" for k, v in sorted(by_section.items())))
        return 1
    print("No diffs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
