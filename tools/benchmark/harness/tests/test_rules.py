from pathlib import Path

from engines.python.loader import load_pack
from tools.benchmark.harness.rules import build_rules

PLATFORM_ROOT = Path(__file__).resolve().parents[4]
PACKS_DIR = PLATFORM_ROOT / "packs"


def _load(pack_id: str, level_id: str):
    game_def, levels = load_pack(str(PACKS_DIR / pack_id))
    return game_def, levels[level_id]


def test_rules_mention_each_action_id():
    game_def, level_def = _load("number_cells", "nc_001")
    text = build_rules(game_def, level_def, goals_text="reach the goal")
    for action in game_def.actions:
        assert action["id"] in text


def test_rules_include_goal_text():
    game_def, level_def = _load("number_cells", "nc_001")
    text = build_rules(game_def, level_def, goals_text="SENTINEL GOAL")
    assert "SENTINEL GOAL" in text


def test_rules_document_the_play_verbs():
    game_def, level_def = _load("number_cells", "nc_001")
    text = build_rules(game_def, level_def, goals_text="g")
    for verb in ("./play state", "./play move", "./play history", "./play give_up"):
        assert verb in text


def test_rules_leak_no_gold_path():
    game_def, level_def = _load("number_cells", "nc_001")
    text = build_rules(game_def, level_def, goals_text="g").lower()
    for banned in ("goldpath", "gold_path", "gold path", "solution"):
        assert banned not in text


def test_rules_leak_no_move_count():
    """The number of moves in the intended solution must not appear."""
    game_def, level_def = _load("number_cells", "nc_001")
    gold_len = len(level_def["solution"]["goldPath"])
    text = build_rules(game_def, level_def, goals_text="g")
    assert f"{gold_len} moves" not in text
    assert f"{gold_len} actions" not in text
