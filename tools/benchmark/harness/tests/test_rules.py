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


# ── generated examples must be JSON an agent can paste back ──────────────

import json  # noqa: E402

import pytest  # noqa: E402


class _FakeGameDef:
    """Minimal stand-in: no pack ships an apostrophe today, but nothing stops one."""

    description = ""

    def __init__(self, actions):
        self.actions = actions


def _json_snippets(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        if line.startswith("Shape: `") or "./play move '" in line:
            start = line.index("{")
            out.append(line[start:line.rindex("}") + 1])
    return out


@pytest.mark.parametrize("value", ["O'Reilly", 'say "hi"', "back\\slash", "a\nb"])
def test_examples_stay_valid_json_for_awkward_values(value):
    game_def = _FakeGameDef(
        [{"id": "choose", "params": {"value": {"type": "string", "values": [value]}}}]
    )
    text = build_rules(game_def, {"title": "T"}, goals_text="g")
    snippets = _json_snippets(text)
    assert snippets
    for snippet in snippets:
        assert json.loads(snippet)["value"] == value


def test_examples_stay_valid_json_for_python_literals():
    """str(dict) writes True/None; JSON wants true/null."""
    game_def = _FakeGameDef(
        [{"id": "toggle", "params": {"on": {"type": "boolean", "values": [True]}}}]
    )
    text = build_rules(game_def, {"title": "T"}, goals_text="g")
    for snippet in _json_snippets(text):
        assert json.loads(snippet)["on"] is True


def test_real_pack_examples_parse():
    game_def, level_def = _load("number_cells", "nc_001")
    text = build_rules(game_def, level_def, goals_text="g")
    snippets = _json_snippets(text)
    assert len(snippets) >= 2
    for snippet in snippets:
        assert "action" in json.loads(snippet)


def test_anon_rules_document_aliases_and_hide_real_ids():
    game_def, level_def = _load("number_cells", "nc_001")
    from engines.python.anon import build_anon_action_shapes

    shapes, _table = build_anon_action_shapes(game_def)
    text = build_rules(game_def, level_def, goals_text="g",
                       actions=shapes, anonymized=True)
    # Only the action *names* must be hidden. "./play move" is a verb of the
    # client, and stays put whatever the pack happens to call its actions.
    for action in game_def.actions:
        assert f"### `{action['id']}`" not in text
    for shape in shapes:
        assert f"### `{shape['id']}`" in text
    for snippet in _json_snippets(text):
        assert json.loads(snippet)["action"].startswith("a")
