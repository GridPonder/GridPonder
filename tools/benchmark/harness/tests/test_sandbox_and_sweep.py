"""Isolation, retry-on-loss, the sweep, and the PDF report.

The isolation tests are the load-bearing ones. Everything the protocol withholds
is worthless if the agent can read the pack off disk, so these assert the
negative directly — from inside the confinement, against the real pack path —
rather than trusting the bind list to be right.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS_DIR = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = HARNESS_DIR.parents[2]
SUPERVISOR = HARNESS_DIR / "supervisor.py"
SWEEP = HARNESS_DIR / "sweep.py"
REPORT = HARNESS_DIR / "report.py"

if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from tools.benchmark.harness import agents, isolation  # noqa: E402

# The tests directory is not a package, so this shares fixtures with its sibling
# the same way pytest imports it: by name, off the directory it lives in.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_end_to_end import LEVELS, _requires, gold_path  # noqa: E402

pytestmark = pytest.mark.skipif(
    not isolation.available("bwrap"),
    reason="bubblewrap or unprivileged user namespaces unavailable",
)


# ── the sandbox is actually a sandbox ─────────────────────────────────────

def test_pack_is_unreachable_from_inside(tmp_path):
    packs_dir = _requires("three_kingdoms")
    sandbox = tmp_path / "sbx"
    sandbox.mkdir()
    level = packs_dir / "three_kingdoms" / "levels" / "tk_001.json"
    assert level.is_file(), "precondition: the level exists on the host"

    argv = isolation.wrap(
        ["/usr/bin/python3", "-c",
         "import sys; print(open(sys.argv[1]).read())", str(level)],
        sandbox=sandbox,
    )
    proc = subprocess.run(argv, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "goldPath" not in proc.stdout


def test_verify_rejects_a_reachable_pack(tmp_path):
    """The guard has to fail when the pack *is* reachable, or it guards nothing."""
    packs_dir = _requires("three_kingdoms")
    sandbox = tmp_path / "sbx"
    sandbox.mkdir()
    isolation.verify(sandbox, packs_dir / "three_kingdoms")  # passes: outside

    # A path inside the sandbox is reachable by construction.
    reachable = sandbox / "decoy.json"
    reachable.write_text("{}")
    with pytest.raises(isolation.IsolationUnavailable):
        isolation.verify(sandbox, reachable)


def test_isolation_none_is_not_confined(tmp_path):
    """`--isolation none` must be transparent, so nothing silently relies on it."""
    assert isolation.wrap(["echo", "hi"], sandbox=tmp_path, mode="none") == ["echo", "hi"]


def test_the_repo_itself_is_hidden(tmp_path):
    """Not just the pack: the engine and solver would answer the puzzle too."""
    sandbox = tmp_path / "sbx"
    sandbox.mkdir()
    argv = isolation.wrap(
        ["/usr/bin/python3", "-c",
         "import os,sys; sys.exit(0 if not os.path.exists(sys.argv[1]) else 1)",
         str(PLATFORM_ROOT / "engines")],
        sandbox=sandbox,
    )
    assert subprocess.run(argv, capture_output=True).returncode == 0


# ── losing and trying again ───────────────────────────────────────────────

def run_supervisor(tmp_path, packs_dir, pack, level, *, agent="baseline",
                   max_attempts=1, seed=0, extra=()):
    sandbox = tmp_path / f"{pack}_{level}"
    result_path = tmp_path / f"{pack}_{level}.json"
    argv = [
        sys.executable, str(SUPERVISOR),
        "--pack", pack, "--level", level,
        "--packs-dir", str(packs_dir),
        "--sandbox", str(sandbox), "--result", str(result_path),
        "--agent", agent, "--max-attempts", str(max_attempts),
        "--seed", str(seed), "--timeout", "120", *extra,
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    return json.loads(result_path.read_text())


@pytest.mark.parametrize("pack,level", LEVELS)
def test_one_attempt_still_ends_the_run_on_a_loss(tmp_path, pack, level):
    """The historical behaviour has to survive, since bench.py relies on it."""
    packs_dir = _requires(pack)
    result = run_supervisor(tmp_path, packs_dir, pack, level, max_attempts=1)
    assert result["attempts"] == 1
    assert result["losses"] <= 1
    assert result["max_attempts"] == 1


def test_losing_costs_an_attempt_instead_of_the_run(tmp_path):
    """tk_006 caps actions at 20, so a flailing agent loses and gets restarted."""
    packs_dir = _requires("three_kingdoms")
    result = run_supervisor(tmp_path, packs_dir, "three_kingdoms", "tk_006",
                            max_attempts=3)
    assert result["max_attempts"] == 3
    assert result["losses"] >= 1, "a random agent must trip tk_006's action cap"
    assert result["attempts"] > 1, "a loss must restart rather than end the run"
    assert result["attempts"] <= 3


def test_a_gold_path_run_never_loses(tmp_path):
    """Retries must not change a clean run: still one attempt, no losses."""
    packs_dir = _requires("three_kingdoms")
    gold = gold_path(packs_dir, "three_kingdoms", "tk_006")
    sandbox = tmp_path / "gold"
    result_path = tmp_path / "gold.json"
    scripted = Path(__file__).resolve().parent / "scripted_agent.py"
    proc = subprocess.run([
        sys.executable, str(SUPERVISOR),
        "--pack", "three_kingdoms", "--level", "tk_006",
        "--packs-dir", str(packs_dir), "--sandbox", str(sandbox),
        "--result", str(result_path), "--max-attempts", "3",
        "--isolation", "none",
        "--agent-cmd", sys.executable, str(scripted), json.dumps(gold),
    ], capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    result = json.loads(result_path.read_text())
    assert result["solved"] is True
    assert result["losses"] == 0
    assert result["attempts"] == 1


def test_probing_no_longer_kills_the_run_before_it_starts(tmp_path):
    """Five illegal moves in a row is exploration, not grounds for ending a run.

    A pack that makes you select a piece before moving it produces exactly that
    while the agent hunts for the selectable cell. Sharing one guard with the
    malformed-JSON counter ended those runs at zero actions.
    """
    from tools.benchmark import runner

    assert runner._MAX_CONSECUTIVE_ILLEGAL > runner._MAX_CONSECUTIVE_SCHEMA

    packs_dir = _requires("pincer")
    gold = gold_path(packs_dir, "pincer", "pc_006")
    # Six taps on a wall, then the real solution.
    probes = [{"action": "tap_cell", "position": [0, 1]}] * 6
    sandbox = tmp_path / "probe"
    result_path = tmp_path / "probe.json"
    scripted = Path(__file__).resolve().parent / "scripted_agent.py"
    proc = subprocess.run([
        sys.executable, str(SUPERVISOR),
        "--pack", "pincer", "--level", "pc_006",
        "--packs-dir", str(packs_dir), "--sandbox", str(sandbox),
        "--result", str(result_path), "--isolation", "none",
        "--agent-cmd", sys.executable, str(scripted), json.dumps(probes + gold),
    ], capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    result = json.loads(result_path.read_text())
    assert result["rejected_illegal"] >= 6
    assert result["solved"] is True, (
        "probing must not end the run before the agent can play"
    )


# ── sweep and report ──────────────────────────────────────────────────────

def test_sweep_writes_results_and_report_renders_a_pdf(tmp_path):
    packs_dir = _requires("three_kingdoms")
    out = tmp_path / "run"
    proc = subprocess.run([
        sys.executable, str(SWEEP),
        "--packs-dir", str(packs_dir), "--out", str(out),
        "--agent", "baseline", "--pack", "three_kingdoms",
        "--level", "tk_001", "--level", "tk_006",
        "--repeats", "2", "--concurrency", "2", "--timeout", "120",
    ], capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"

    payload = json.loads((out / "results.json").read_text())
    assert payload["meta"]["sessions"] == 4
    assert len(payload["runs"]) == 4
    # The baseline ignores --model, so the tier's model must not be recorded.
    assert payload["meta"]["model"] is None
    assert {r["level_id"] for r in payload["runs"]} == {"tk_001", "tk_006"}
    for run in payload["runs"]:
        assert "losses" in run and "attempts" in run

    pdf = out / "report.pdf"
    proc = subprocess.run(
        [sys.executable, str(REPORT), str(out / "results.json"), "-o", str(pdf)],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert pdf.is_file() and pdf.stat().st_size > 5000
    assert pdf.read_bytes()[:5] == b"%PDF-"


def test_a_failed_session_is_reported_not_dropped(tmp_path):
    """A crashed session must still count as an unsolved run.

    Dropping it shrinks the denominator, which makes the agent look better the
    more often the harness breaks.
    """
    from tools.benchmark.harness.sweep import run_one

    result = run_one({
        "pack": "three_kingdoms", "level": "no_such_level", "repeat": 0,
        "packs_dir": str(_requires("three_kingdoms")),
        "sandbox": str(tmp_path / "sbx"),
        "result_path": str(tmp_path / "r.json"),
        "config": str(HARNESS_DIR / "harness.yaml"),
        "agent": "baseline", "model": None, "isolation": "none",
        "max_attempts": 1, "timeout": 60, "anon": False,
    })
    assert result["solved"] is False
    assert result["tier"] == "error"
    assert result["error"]


def test_report_summarizes_repeats_into_one_row_per_level():
    from tools.benchmark.harness import report

    runs = [
        {"pack_id": "p", "level_id": "l1", "solved": True, "efficiency": 1.0,
         "losses": 0, "attempts": 1, "actions_total": 5, "gold_path_length": 5,
         "rejected_schema": 0, "rejected_illegal": 0, "tier": "trivial"},
        {"pack_id": "p", "level_id": "l1", "solved": False, "efficiency": 3.0,
         "losses": 2, "attempts": 3, "actions_total": 15, "gold_path_length": 5,
         "rejected_schema": 0, "rejected_illegal": 4, "tier": "hard"},
    ]
    rows = report.summarize(runs)
    assert len(rows) == 1
    row = rows[0]
    assert row["solved"] == 1 and row["runs"] == 2
    assert row["solve_rate"] == 0.5
    assert row["losses"] == 1.0
    # Efficiency averages solved runs only: the unsolved run stopped at the
    # action budget, so folding it in would describe a level nobody finished.
    assert row["efficiency"] == 1.0
    # Worst tier wins, so a level that failed once is not averaged into looking fine.
    assert report._dominant_tier(row["tiers"]) == "hard"


# ── adapters ──────────────────────────────────────────────────────────────

def test_claude_adapter_never_names_the_pack_in_its_credentials():
    spec = agents.build("claude", model="haiku")
    assert spec.uses_model is True
    for path in list(spec.credentials) + list(spec.tools):
        assert "packs" not in str(path), f"adapter exposes {path}"


def test_baseline_adapter_declares_no_model():
    assert agents.build("baseline").uses_model is False


def test_usage_parsing_is_best_effort():
    assert agents.parse_usage("") == {}
    assert agents.parse_usage("not json at all") == {}
    parsed = agents.parse_usage(json.dumps({
        "usage": {"input_tokens": 12, "output_tokens": 3},
        "total_cost_usd": 0.004, "num_turns": 7,
    }))
    assert parsed["input_tokens"] == 12
    assert parsed["cost_usd"] == 0.004
    assert parsed["turns"] == 7


def test_unknown_agent_is_an_error():
    with pytest.raises(ValueError):
        agents.build("nope")


def test_agent_history_is_not_readable_from_the_sandbox(tmp_path):
    """The agent's own tool history must not be a back channel to the answers.

    ~/.claude holds a transcript of every past session. On this repo those
    sessions print gold paths while debugging levels, so binding the directory
    wholesale let an agent with Bash grep the solution out of its own history
    and "solve" a level it never played.
    """
    sandbox = tmp_path / "sbx"
    sandbox.mkdir()
    spec = agents.build("claude", model="haiku")

    for path in spec.credentials:
        assert path.name != ".claude" or path.is_dir(), path

    probe = (
        "import os,sys;"
        "home=os.path.expanduser('~');"
        "sys.exit(1 if os.path.isdir(os.path.join(home,'.claude','projects')) else 0)"
    )
    argv = isolation.wrap(["/usr/bin/python3", "-c", probe], sandbox=sandbox,
                          credentials=spec.credentials, tools=spec.tools)
    assert subprocess.run(argv, capture_output=True).returncode == 0, (
        "the agent can read ~/.claude/projects, which contains past transcripts"
    )


# ── docker isolation ──────────────────────────────────────────────────────

_DOCKER = pytest.mark.skipif(
    not isolation.available("docker"),
    reason="docker unavailable or its daemon is unreachable",
)


@_DOCKER
def test_docker_refuses_a_missing_image(tmp_path):
    """A missing image must fail before the run, not mid-sweep."""
    with pytest.raises(isolation.IsolationUnavailable) as excinfo:
        isolation.wrap(["true"], sandbox=tmp_path, mode="docker",
                       image="gridponder-does-not-exist:never")
    assert "docker build" in str(excinfo.value)


@_DOCKER
def test_docker_command_mounts_only_what_was_asked_for(tmp_path):
    """The mount list is the whole boundary, so assert its shape directly."""
    sandbox = (tmp_path / "sbx").resolve()
    sandbox.mkdir()
    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    cred_dir = tmp_path / "creddir"
    cred_dir.mkdir()

    argv = isolation.wrap(
        ["agent"], sandbox=sandbox, mode="docker", image="gridponder-harness:test",
        credentials=[cred_dir, creds], network="none", memory="1g", cpus="2",
    )
    joined = " ".join(argv)
    assert "--network=none" in joined
    assert "--memory=1g" in joined and "--cpus=2" in joined
    assert "--cap-drop ALL" in joined
    assert f"-v {sandbox}:{sandbox}" in joined
    assert f"-v {creds}:{creds}" in joined
    # A credential *directory* becomes an empty tmpfs, never a mount: it would
    # otherwise carry the agent's own session history into the sandbox.
    assert f"--tmpfs {cred_dir}:exec" in joined
    assert f"-v {cred_dir}" not in joined
    # Nothing from this repo may appear anywhere in the command.
    assert str(PLATFORM_ROOT / "engines") not in joined


@pytest.fixture
def docker_sandbox():
    """A sandbox docker can actually mount.

    pytest's tmp_path lives under /tmp, and a daemon started with PrivateTmp
    bind-mounts an empty directory from there instead of the host's, so the
    agent sees nothing. Keep docker sandboxes off /tmp.
    """
    import shutil as _shutil
    import uuid

    root = PLATFORM_ROOT / "tmp" / "docker-tests" / uuid.uuid4().hex[:8]
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        _shutil.rmtree(root, ignore_errors=True)


@_DOCKER
def test_docker_reports_a_sandbox_it_cannot_mount(tmp_path):
    """A mount that silently fails must not read as a badly played run."""
    if not isolation.image_exists("gridponder-harness:test"):
        pytest.skip("build gridponder-harness:test to exercise docker mode")
    sandbox = tmp_path / "sbx"          # under /tmp on purpose
    sandbox.mkdir()
    try:
        isolation.verify(sandbox, PLATFORM_ROOT / "engines", mode="docker",
                         image="gridponder-harness:test")
    except isolation.IsolationUnavailable as exc:
        assert "not visible inside the confinement" in str(exc)
    else:
        # A daemon without PrivateTmp mounts /tmp fine; then there is nothing
        # to catch and the positive control simply passes.
        pass


@_DOCKER
def test_docker_hides_the_pack_and_the_repo(docker_sandbox):
    if not isolation.image_exists("gridponder-harness:test"):
        pytest.skip("build gridponder-harness:test to exercise docker mode")
    packs_dir = _requires("three_kingdoms")
    sandbox = docker_sandbox / "sbx"
    sandbox.mkdir()
    isolation.verify(sandbox, packs_dir / "three_kingdoms", mode="docker",
                     image="gridponder-harness:test")
    isolation.verify(sandbox, PLATFORM_ROOT / "engines", mode="docker",
                     image="gridponder-harness:test")


@_DOCKER
def test_docker_runs_a_whole_game(docker_sandbox):
    """The socket has to survive the container boundary, not just the mounts."""
    if not isolation.image_exists("gridponder-harness:test"):
        pytest.skip("build gridponder-harness:test to exercise docker mode")
    packs_dir = _requires("three_kingdoms")
    result = run_supervisor(
        docker_sandbox, packs_dir, "three_kingdoms", "tk_006", max_attempts=3,
        extra=("--isolation", "docker",
               "--docker-image", "gridponder-harness:test"),
    )
    assert result["isolation"] == "docker"
    assert result["actions_total"] > 0, "the agent could not reach the socket"
    assert result["reached_terminal"] is True


# ── the reasoning appendix ────────────────────────────────────────────────

def _assistant(blocks):
    return json.dumps({"type": "assistant",
                       "message": {"role": "assistant", "content": blocks}})


def test_reasoning_survives_text_and_calls_arriving_separately(tmp_path):
    """The real CLI splits narration and tool calls across messages.

    Pairing a call with only its own message therefore yields a blank quote on
    almost every obstacle, which is the difference between a useful appendix
    and an empty one.
    """
    from tools.benchmark.harness import timeline

    stream = "\n".join([
        _assistant([{"type": "text", "text": "First I will look at the board."}]),
        _assistant([{"type": "tool_use", "id": "1", "name": "Bash",
                     "input": {"command": "./play state"}}]),
        _assistant([{"type": "text", "text": "Now I will move left."}]),
        _assistant([{"type": "tool_use", "id": "2", "name": "Bash",
                     "input": {"command": "./play move '{\"action\":\"move\"}'"}}]),
    ])
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join([
        json.dumps({"seq": 0, "verb": "state", "args": [], "took": 0.1}),
        json.dumps({"seq": 1, "verb": "move", "args": ["{}"], "took": 0.2,
                    "rejected_illegal": 1}),
    ]))
    transcript.with_suffix(".agent.jsonl").write_text(stream)

    summary = timeline.summarize(transcript)
    assert [b["text"] for b in summary["narrative"] if b["text"]] == [
        "First I will look at the board.", "Now I will move left."]
    obstacle = summary["obstacles"][0]
    assert obstacle["reasoning"] == "Now I will move left.", (
        "an obstacle must quote the reasoning that led to it"
    )


# ── what an attempt is worth ──────────────────────────────────────────────

def test_full_attempts_gives_each_attempt_the_levels_own_budget(tmp_path):
    """tk_008 caps an attempt at 21 actions; its gold path is 18 long.

    Under one shared budget of 3 x 18 = 54, the first two attempts consume 42
    and the third begins with 12 — fewer than the 18 a perfect solve needs. So
    the third attempt is unwinnable before it starts, and "3 attempts" measures
    budget arithmetic rather than the puzzle. Full attempts spend 3 x 21 = 63
    and every attempt is a real second chance.
    """
    packs_dir = _requires("three_kingdoms")
    shared = run_supervisor(tmp_path / "shared", packs_dir, "three_kingdoms",
                            "tk_008", max_attempts=3, extra=("--shared-budget",))
    full = run_supervisor(tmp_path / "full", packs_dir, "three_kingdoms",
                          "tk_008", max_attempts=3, extra=("--full-attempts",))

    assert shared["full_attempts"] is False and full["full_attempts"] is True
    assert shared["actions_total"] == 54, "3 x the 18-move gold path"
    assert full["actions_total"] == 63, "3 x the level's own 21-action cap"
    # The tell that the shared budget truncates: the last attempt is cut off by
    # the run total before it can reach the cap that would have lost it.
    assert full["losses"] == 3, "every attempt must run into the level's cap"
    assert shared["losses"] < 3


def test_level_cap_comes_from_the_lose_condition_not_a_multiplier():
    """The budget a human plays against is the one the level declares."""
    from tools.benchmark.runner import _level_action_cap

    assert _level_action_cap({"loseConditions": [
        {"type": "balance_unreachable", "config": {"goalId": "g"}},
        {"type": "max_actions", "config": {"limit": 21}},
    ]}) == 21
    assert _level_action_cap({"loseConditions": []}) is None
    assert _level_action_cap({}) is None
    # A malformed limit must not become a budget of zero, which would end every
    # attempt before it began.
    assert _level_action_cap({"loseConditions": [
        {"type": "max_actions", "config": {"limit": "21"}}]}) is None


# ── catching the agent's reasoning ────────────────────────────────────────

def test_a_thinking_budget_is_requested_only_when_asked_for():
    """Off by default, because it makes the transcript worse rather than better.

    The CLI strips thinking blocks to an empty string, so a forced budget moves
    the reasoning somewhere we cannot read and takes the plain-text narration
    with it. The knob survives because a bigger budget is a real property of a
    run, not because it helps anyone read one.
    """
    assert "MAX_THINKING_TOKENS" not in agents.build("claude").env
    spec = agents.build("claude", thinking_tokens=6000)
    assert spec.env["MAX_THINKING_TOKENS"] == "6000"
    # Every adapter takes the same arguments, so the sweep never has to know
    # which of them can use one.
    agents.build("baseline", thinking_tokens=6000, narrate=True)


def test_the_reason_travels_with_the_move_and_reaches_the_transcript(tmp_path):
    """The reasoning channel is the protocol, not the agent's output stream.

    Asking in the launch prompt was tried and failed: Claude Code answers into
    thinking blocks and strips their contents, so the request produced nothing.
    A second argument to `move` cannot be redacted, arrives attached to the
    move it explains, and works the same for every adapter.
    """
    packs_dir = _requires("three_kingdoms")
    gold = gold_path(packs_dir, "three_kingdoms", "tk_006")
    sandbox = tmp_path / "sbx"
    transcript = tmp_path / "s.jsonl"
    scripted = Path(__file__).resolve().parent / "scripted_agent.py"
    proc = subprocess.run([
        sys.executable, str(SUPERVISOR),
        "--pack", "three_kingdoms", "--level", "tk_006",
        "--packs-dir", str(packs_dir), "--sandbox", str(sandbox),
        "--transcript", str(transcript), "--isolation", "none", "--narrate",
        "--agent-cmd", sys.executable, str(scripted), json.dumps(gold),
    ], capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"

    # RULES.md is where it is documented, so every harness learns about it.
    rules = (sandbox / "RULES.md").read_text()
    assert "second argument" in rules

    # The scripted agent sends no reason; the field must still exist and be
    # empty rather than absent, and a missing reason must never be a rejection.
    rows = [json.loads(line) for line in
            transcript.read_text().splitlines() if line.strip()]
    moves = [r for r in rows if r["verb"] == "move"]
    assert moves and all("why" in r for r in moves)
    assert json.loads((tmp_path / "s.jsonl").with_suffix(".jsonl").read_text()
                      .splitlines()[0])["why"] == ""


def test_a_stated_reason_beats_one_scraped_from_the_stream(tmp_path):
    """Two channels, and they can disagree. The stated one wins.

    The scraped one is aligned by position and can only ever be the agent's
    last remark before the call; the stated one was written for that move.
    """
    from tools.benchmark.harness import timeline

    stream = "\n".join([
        _assistant([{"type": "text", "text": "Some earlier musing."}]),
        _assistant([{"type": "tool_use", "id": "1", "name": "Bash",
                     "input": {"command": "./play move '{\"action\":\"a\"}'"}}]),
    ])
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({
        "seq": 0, "verb": "move", "args": ["{}", "corner first"],
        "why": "corner first", "took": 0.1, "rejected_illegal": 1,
        "response": "Rejected"}))
    transcript.with_suffix(".agent.jsonl").write_text(stream)

    summary = timeline.summarize(transcript)
    assert summary["obstacles"][0]["reasoning"] == "corner first"
    assert summary["obstacles"][0]["reasoning_fresh"] is True
    assert summary["coverage"]["ratio"] == 1.0
    # And it shows up in the appendix as the agent's own words, marked as
    # stated rather than inferred.
    thought = [e for e in summary["dialogue"] if e["kind"] == "thought"]
    assert {"corner first"} <= {t["text"] for t in thought}
    assert any(t.get("stated") for t in thought)


@_DOCKER
def test_docker_forwards_the_environment_the_adapter_asked_for(tmp_path):
    """A container inherits nothing from the caller's shell.

    An unforwarded API key does not fail as a configuration error; it fails as
    an agent that could not authenticate, which reads like a bad run. bwrap
    inherits the environment and hid this for as long as it was the only mode.
    """
    sandbox = (tmp_path / "sbx").resolve()
    sandbox.mkdir()
    argv = isolation.wrap(
        ["agent"], sandbox=sandbox, mode="docker",
        image="gridponder-harness:test", network="none",
        env={"ANTHROPIC_API_KEY": "sk-test", "MAX_THINKING_TOKENS": "6000"},
    )
    joined = " ".join(argv)
    assert "--env ANTHROPIC_API_KEY=sk-test" in joined
    assert "--env MAX_THINKING_TOKENS=6000" in joined
    # Only what was named. Forwarding os.environ wholesale would put this
    # repo's own paths back inside the container.
    assert "PATH=" not in joined


def test_a_silent_move_is_not_given_someone_elses_reasons(tmp_path):
    """Carrying text forward is right; presenting it as fresh is not.

    A move made without narration inherits the previous move's quote, and an
    unlabelled quote attributes a reason to a decision the agent never
    explained — which is worse than admitting the gap, because it is the moves
    made in silence that a reader most wants to find.
    """
    from tools.benchmark.harness import timeline

    stream = "\n".join([
        _assistant([{"type": "text", "text": "Left looks safe."}]),
        _assistant([{"type": "tool_use", "id": "1", "name": "Bash",
                     "input": {"command": "./play move '{\"action\":\"a\"}'"}}]),
        # No narration at all before the second move.
        _assistant([{"type": "tool_use", "id": "2", "name": "Bash",
                     "input": {"command": "./play move '{\"action\":\"b\"}'"}}]),
    ])
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join([
        json.dumps({"seq": 0, "verb": "move", "args": ["{}"], "took": 0.1,
                    "response": "ok"}),
        json.dumps({"seq": 1, "verb": "move", "args": ["{}"], "took": 0.1,
                    "rejected_illegal": 1, "response": "Rejected — not legal"}),
    ]))
    transcript.with_suffix(".agent.jsonl").write_text(stream)

    summary = timeline.summarize(transcript)
    assert summary["turns"] == 2
    silent = summary["obstacles"][0]
    assert silent["reasoning"] == "Left looks safe."
    assert silent["reasoning_fresh"] is False, (
        "a move made in silence must be marked, not quoted as if explained")
    assert summary["coverage"] == {"calls": 2, "explained": 1, "ratio": 0.5}


def test_a_timed_out_agent_still_leaves_its_reasoning(tmp_path):
    """subprocess.run discards what it captured when it kills a child.

    The run most likely to hit the timeout is the long, hard one — the run
    whose transcript is worth the most — so the stream goes to disk as it
    arrives rather than being handed over at the end.
    """
    packs_dir = _requires("three_kingdoms")
    chatty = tmp_path / "chatty.py"
    chatty.write_text(
        "import json, time\n"
        "print(json.dumps({'type': 'assistant', 'message': {'content': ["
        "{'type': 'text', 'text': 'still working on the board'}]}}), flush=True)\n"
        "time.sleep(300)\n"
    )
    transcript = tmp_path / "s.jsonl"
    proc = subprocess.run([
        sys.executable, str(SUPERVISOR),
        "--pack", "three_kingdoms", "--level", "tk_008",
        "--packs-dir", str(packs_dir), "--sandbox", str(tmp_path / "sbx"),
        "--transcript", str(transcript), "--isolation", "none", "--timeout", "3",
        "--agent-cmd", sys.executable, str(chatty),
    ], capture_output=True, text=True, timeout=120)

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    stream = transcript.with_suffix(".agent.jsonl")
    assert stream.is_file(), "a killed agent must still leave its stream"
    assert "still working on the board" in stream.read_text()


def test_dialogue_puts_the_reply_next_to_the_command_that_earned_it(tmp_path):
    """Half a conversation is the wrong half.

    An agent trips where its expectation and the board come apart, so a reader
    needs the reasoning, the command and the reply adjacent. They live in two
    transcripts written by two processes; this is what joins them.
    """
    from tools.benchmark.harness import timeline

    stream = "\n".join([
        _assistant([{"type": "thinking", "thinking": "The wall is to my left."}]),
        _assistant([{"type": "tool_use", "id": "1", "name": "Bash",
                     "input": {"command": "./play move '{\"action\":\"a\"}'"}}]),
    ])
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({
        "seq": 0, "verb": "move", "args": ["{}"], "took": 0.1,
        "rejected_illegal": 1, "response": "Rejected — not a legal move"}))
    transcript.with_suffix(".agent.jsonl").write_text(stream)

    merged = timeline.summarize(transcript)["dialogue"]
    assert [e["kind"] for e in merged] == ["thought", "call"]
    assert merged[0]["text"] == "The wall is to my left."
    assert merged[1]["verb"] == "move"
    assert merged[1]["turn"]["response"] == "Rejected — not a legal move", (
        "the call has to carry the reply it got, or the appendix shows the "
        "agent's plans with no record of how they landed")


def test_usage_is_parsed_from_a_stream(tmp_path):
    """stream-json puts the tally in a final event, not in the whole payload."""
    stream = "\n".join([
        _assistant([{"type": "text", "text": "hi"}]),
        json.dumps({"type": "result", "subtype": "success",
                    "total_cost_usd": 0.5, "num_turns": 3,
                    "usage": {"input_tokens": 10, "output_tokens": 20}}),
    ])
    parsed = agents.parse_usage(stream)
    assert parsed["cost_usd"] == 0.5
    assert parsed["input_tokens"] == 10 and parsed["turns"] == 3
