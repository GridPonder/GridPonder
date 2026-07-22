from tools.benchmark.harness import metrics

T = {"efficiency_trivial_max": 1.5, "rejected_friction_min": 5}


def _run(**kw) -> dict:
    base = {"solved": True, "actions_total": 10, "gold_path_length": 10,
            "attempts": 1, "rejected_count": 0}
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


def test_failure_with_many_rejections_is_friction():
    assert metrics.classify(_run(solved=False, rejected_count=5), T) == "friction"


def test_friction_beats_hard_regardless_of_attempts():
    run = _run(solved=False, rejected_count=99, attempts=4)
    assert metrics.classify(run, T) == "friction"


def test_successful_run_with_many_rejections_is_not_trivial():
    """Rejections mean the agent was guessing at the schema — not a clean solve."""
    assert metrics.classify(_run(rejected_count=5), T) == "friction"
