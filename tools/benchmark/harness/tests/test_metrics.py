from tools.benchmark.harness import metrics

T = {"efficiency_trivial_max": 1.5, "rejected_friction_min": 5}


def _run(**kw) -> dict:
    base = {"solved": True, "actions_total": 10, "gold_path_length": 10,
            "attempts": 1, "rejected_schema": 0, "rejected_illegal": 0}
    base.update(kw)
    return base


# ── first_divergence ──────────────────────────────────────────────────────

def test_divergence_at_first_differing_move():
    gold = [{"action": "a"}, {"action": "b"}, {"action": "c"}]
    agent = [{"action": "a"}, {"action": "x"}]
    assert metrics.first_divergence(agent, gold) == 1


def test_no_divergence_when_agent_follows_prefix():
    gold = [{"action": "a"}, {"action": "b"}, {"action": "c"}]
    assert metrics.first_divergence([{"action": "a"}], gold) is None


def test_divergence_at_zero_when_first_move_differs():
    assert metrics.first_divergence([{"action": "z"}], [{"action": "a"}]) == 0


def test_agent_longer_than_gold_diverges_at_gold_length():
    gold = [{"action": "a"}]
    agent = [{"action": "a"}, {"action": "b"}]
    assert metrics.first_divergence(agent, gold) == 1


def test_empty_agent_path_has_no_divergence():
    assert metrics.first_divergence([], [{"action": "a"}]) is None


# ── efficiency ────────────────────────────────────────────────────────────

def test_efficiency_is_ratio():
    assert metrics.efficiency(15, 10) == 1.5


def test_efficiency_none_when_gold_length_zero():
    assert metrics.efficiency(15, 0) is None


# ── classify ──────────────────────────────────────────────────────────────

def test_clean_first_attempt_solve_is_trivial():
    assert metrics.classify(_run(), T) == "trivial"


def test_solve_at_efficiency_boundary_is_trivial():
    assert metrics.classify(_run(actions_total=15), T) == "trivial"


def test_wandering_solve_is_borderline():
    assert metrics.classify(_run(actions_total=16), T) == "borderline"


def test_multi_attempt_solve_is_borderline():
    assert metrics.classify(_run(attempts=2), T) == "borderline"


def test_clean_failure_is_hard():
    assert metrics.classify(_run(solved=False), T) == "hard"


def test_failure_with_many_schema_rejections_is_friction():
    assert metrics.classify(_run(solved=False, rejected_schema=5), T) == "friction"


def test_friction_beats_hard_regardless_of_attempts():
    run = _run(solved=False, rejected_schema=99, attempts=4)
    assert metrics.classify(run, T) == "friction"


def test_successful_run_with_many_schema_rejections_is_friction():
    """Malformed JSON means the agent was guessing at the schema, solve or not."""
    assert metrics.classify(_run(rejected_schema=5), T) == "friction"


# ── the distinction comment 3 asked for ───────────────────────────────────

def test_illegal_moves_never_make_a_solved_run_friction():
    """Probing walls is how you read a board. It is not a schema defect."""
    assert metrics.classify(_run(rejected_illegal=99), T) == "trivial"


def test_illegal_moves_do_not_hide_a_genuine_failure():
    assert metrics.classify(_run(solved=False, rejected_illegal=99), T) == "hard"


def test_schema_and_illegal_counters_are_independent():
    """Below the schema threshold, illegal count cannot push a run into friction."""
    run = _run(solved=False, rejected_schema=4, rejected_illegal=50)
    assert metrics.classify(run, T) == "hard"


# ── the run that never finished ───────────────────────────────────────────
#
# `hard` is a claim about the level. A run we killed, or one whose agent died,
# supports no such claim, and counting it as difficulty is how a rate-limited
# sweep turns into a page of hard levels.

def test_unfinished_run_is_incomplete_not_hard():
    assert metrics.classify(_run(solved=False, reached_terminal=False), T) == "incomplete"


def test_a_finished_loss_is_still_hard():
    """The game itself ending the run is a real result about the level."""
    assert metrics.classify(_run(solved=False, reached_terminal=True), T) == "hard"


def test_a_run_without_the_flag_is_treated_as_finished():
    """Older results carry no `reached_terminal`; they must not all become incomplete."""
    assert metrics.classify(_run(solved=False), T) == "hard"


def test_a_solve_is_never_incomplete():
    """Reaching the win is reaching a terminal, whatever the agent did after."""
    assert metrics.classify(_run(solved=True, reached_terminal=False), T) == "trivial"


def test_friction_wins_over_incomplete():
    """Five malformed payloads is a fact about the rules text either way."""
    run = _run(solved=False, reached_terminal=False, rejected_schema=5)
    assert metrics.classify(run, T) == "friction"


# ── how the run stopped ───────────────────────────────────────────────────

def test_completion_of_a_solved_run_is_solved():
    assert metrics.completion(_run(solved=True)) == "solved"


def test_completion_says_the_game_ended_a_finished_run():
    assert metrics.completion(_run(solved=False, reached_terminal=True)) == (
        "the game ended the run"
    )


def test_completion_names_the_timeout():
    run = _run(solved=False, reached_terminal=False, agent_exit_code=-1)
    assert metrics.completion(run) == "the agent was stopped at the timeout"


def test_completion_names_a_crashed_agent():
    run = _run(solved=False, reached_terminal=False, agent_exit_code=2)
    assert metrics.completion(run) == "the agent exited 2"


def test_completion_names_an_agent_that_reported_its_own_error():
    run = _run(solved=False, reached_terminal=False, agent_exit_code=0,
               agent_reported_error=True)
    assert metrics.completion(run) == "the agent reported an error"


def test_completion_of_an_agent_that_simply_stopped():
    run = _run(solved=False, reached_terminal=False, agent_exit_code=0)
    assert metrics.completion(run) == "the agent stopped without finishing"
