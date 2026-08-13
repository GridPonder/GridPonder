"""
Goal text for the `balance` goal type, in clear and anonymous mode.

Without a branch of its own a `balance` goal falls through to the renderer's
default, which emits the goal's *type name* — so an anonymous run was told its
objective was the literal word "balance". Clear mode hid the hole, because a
pack with a `goalDescriptions` override never reaches the default and anonymous
mode skips those overrides by design (the prose names entities).

Builds an inline GameDef and Board directly; goal text only reads state.board.

Run from engines/python/:  python test_goal_renderer.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Board, GameState
from engines.python.anon import build_anon_kind_to_label
from engines.python.goal_renderer import render_goals


def _make_game() -> GameDef:
    data = {
        "id": "com.gridponder.test_goal_renderer",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "territory", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "wall": {"layer": "ground", "tags": ["solid"]},
            "terr_wei": {"layer": "territory", "uiName": "Wei territory"},
            "terr_shu": {"layer": "territory", "uiName": "Shu territory"},
            "terr_wu": {"layer": "territory", "uiName": "Wu territory"},
        },
        "actions": [],
        "systems": [],
    }
    return GameDef.from_dict(data, id="test_goal_renderer")


def _make_state(game: GameDef, territory: list[tuple[int, int, str]],
                size: int = 3) -> GameState:
    level_board = {
        "size": [size, size],
        "layers": {
            "ground": {"format": "sparse", "entries": []},
            "territory": {
                "format": "sparse",
                "entries": [{"position": [x, y], "kind": k} for x, y, k in territory],
            },
        },
    }
    board = Board.from_json(level_board, game.layers)
    return GameState.from_json({}, board, game.defaults)


def _goal(**overrides) -> dict:
    config = {
        "layer": "territory",
        "owners": ["terr_wei", "terr_shu", "terr_wu"],
        "claimableLayer": "ground",
        "claimableKind": "empty",
        "requireComplete": True,
        "requireEqual": True,
    }
    config.update(overrides)
    return {"goals": [{"id": "balance_goal", "type": "balance", "config": config}]}


# Seven of nine cells claimed: 3 Wei, 2 Shu, 2 Wu.
_PARTIAL = [(0, 0, "terr_wei"), (1, 0, "terr_wei"), (2, 0, "terr_wei"),
            (0, 1, "terr_shu"), (1, 1, "terr_shu"),
            (0, 2, "terr_wu"), (1, 2, "terr_wu")]


def _render(level: dict, *, anon: bool = False,
            territory=_PARTIAL) -> str:
    game = _make_game()
    state = _make_state(game, territory)
    labels = build_anon_kind_to_label(game) if anon else None
    return render_goals(level, state, game, anonymize=anon, kind_to_label=labels)


# ── the defect ────────────────────────────────────────────────────────────

def test_balance_is_not_rendered_as_the_word_balance():
    """An agent told its goal is "balance" has been told nothing."""
    text = _render(_goal(), anon=True)
    assert text.strip() != "balance"
    assert len(text) > len("balance")


# ── clear mode ────────────────────────────────────────────────────────────

def test_clear_mode_names_the_owners():
    text = _render(_goal())
    for name in ("Wei territory", "Shu territory", "Wu territory"):
        assert name in text, f"{name!r} missing from {text!r}"


def test_it_asks_for_every_cell_and_an_equal_split():
    text = _render(_goal()).lower()
    assert "every" in text
    assert "equal" in text


def test_progress_is_reported_against_the_claimable_total():
    """Same courtesy sequence_match already gets: say how far along it is."""
    text = _render(_goal())
    assert "7" in text and "9" in text


# ── the flags actually change the sentence ────────────────────────────────

def test_without_require_equal_it_does_not_demand_an_equal_split():
    text = _render(_goal(requireEqual=False)).lower()
    assert "equal" not in text


def test_without_require_complete_it_does_not_demand_every_cell():
    text = _render(_goal(requireComplete=False)).lower()
    assert "every" not in text


# ── anonymous mode ────────────────────────────────────────────────────────

def test_anonymous_mode_uses_aliases_and_never_the_real_names():
    text = _render(_goal(), anon=True)
    for leak in ("Wei", "Shu", "Wu", "terr_wei", "terr_shu", "terr_wu"):
        assert leak not in text, f"{leak!r} leaked into {text!r}"


def test_anonymous_mode_never_names_the_layer():
    """`territory` is the pack's own vocabulary, and aliasing does not cover it."""
    text = _render(_goal(), anon=True)
    assert "territory" not in text.lower()


def test_anonymous_mode_still_says_what_to_do_and_how_far_along():
    text = _render(_goal(), anon=True)
    labels = build_anon_kind_to_label(_make_game())
    for owner in ("terr_wei", "terr_shu", "terr_wu"):
        assert labels[owner] in text
    assert "7" in text and "9" in text


# ── overrides still win in clear mode ─────────────────────────────────────

def test_a_pack_that_wrote_its_own_description_still_gets_it():
    game = _make_game()
    game.goal_descriptions = {"balance_goal": "Split the map three ways."}
    state = _make_state(game, _PARTIAL)
    text = render_goals(_goal(), state, game)
    assert text == "Split the map three ways."


def run_all() -> bool:
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok    {t.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
