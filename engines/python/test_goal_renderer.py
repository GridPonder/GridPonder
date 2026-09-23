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
from engines.python.goal_renderer import describe_loss, join_goal_parts, render_goals


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
    # The override text is kept; the live counts follow it.
    assert text == ("Split the map three ways. (now: Wei territory 3, "
                    "Shu territory 2, Wu territory 2 — 7 of 9 claimed)"), text


# ── board_match target cells ──────────────────────────────────────────────

def _board_match(cell) -> dict:
    """A one-row board_match goal whose single set cell is `cell`."""
    return {"goals": [{
        "id": "match_goal",
        "type": "board_match",
        "config": {"targetLayers": {"territory": [[None, cell, None]]}},
    }]}


def test_board_match_accepts_a_bare_kind():
    text = _render(_board_match("terr_wei"))
    assert "match the target pattern" in text, text
    grid = text.splitlines()[-2]
    # Unset cells are unconstrained under the default exact_non_null mode.
    # (The test kind declares no symbol, so it falls back to "?" too.)
    assert len(grid) == 3 and grid[0] == grid[2] == "?", grid
    assert text.splitlines()[-1] == (
        "Target legend: ?=any (unconstrained), ?=Wei territory"), text


def test_board_match_accepts_the_entry_form():
    """`{"kind": ...}` is the form the spec's own example uses.

    The renderer indexed the cell for a fallback symbol, so this raised
    `KeyError: 0` and took the whole observation with it — which meant any pack
    writing a target cell this way could not be benchmarked at all.
    """
    assert _render(_board_match({"kind": "terr_wei"})) == _render(
        _board_match("terr_wei"))


def test_board_match_entry_form_survives_anonymous_mode():
    """Where it actually bit: clear mode short-circuits on goalDescriptions."""
    text = _render(_board_match({"kind": "terr_wei"}), anon=True)
    assert "match the target pattern" in text, text
    assert "terr_wei" not in text, text


def test_board_match_ignores_a_cell_naming_no_kind():
    assert _render(_board_match({"color": "red"})).splitlines()[-2:] == [
        "???", "Target legend: ?=any (unconstrained)"], \
        _render(_board_match({"color": "red"}))


# ── board_match: wildcard vs required cells, target legend ────────────────

def _symbol_game() -> GameDef:
    data = {
        "id": "com.gridponder.test_target_grid",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
            {"id": "objects", "occupancy": "zero_or_one"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "floor": {"layer": "ground", "symbol": ".", "uiName": "Cut floor"},
            "rock": {"layer": "ground", "symbol": "#"},
            "pod": {"layer": "objects", "symbol": "p", "uiName": "Landed Pod"},
            "digger": {"layer": "actors", "symbol": "1", "uiName": "Digger"},
        },
        "actions": [],
        "systems": [],
    }
    return GameDef.from_dict(data, id="test_target_grid")


def _target_text(target_layers: dict, *, mode: str | None = None,
                 anon: bool = False) -> str:
    game = _symbol_game()
    board = Board.from_json({"size": [3, 2], "layers": {}}, game.layers)
    state = GameState.from_json({}, board, game.defaults)
    config: dict = {"targetLayers": target_layers}
    if mode is not None:
        config["matchMode"] = mode
    level = {"goals": [{"id": "g", "type": "board_match", "config": config}]}
    labels = build_anon_kind_to_label(game) if anon else None
    return render_goals(level, state, game, anonymize=anon, kind_to_label=labels)


def test_unconstrained_cells_render_as_wildcards_and_required_floor_stays_a_dot():
    text = _target_text({"ground": [["floor", None, None], [None, None, None]]})
    assert text.splitlines()[1:] == [
        ".??",
        "???",
        "Target legend: ?=any (unconstrained), .=Cut floor",
    ], text


def test_exact_mode_keeps_dots_for_cells_that_must_be_empty():
    text = _target_text({"objects": [["pod", None, None], [None, None, None]]},
                        mode="exact")
    assert text.splitlines()[1:] == [
        "p..",
        "...",
        "Target legend: .=must be empty, p=Landed Pod",
    ], text


def test_target_legend_names_kinds_absent_from_the_board():
    text = _target_text({"objects": [[None, None, None], [None, "pod", None]]})
    assert "p=Landed Pod" in text, text


def test_composite_cells_show_the_top_layer_and_list_the_rest():
    text = _target_text({
        "ground": [["floor", "rock", None], [None, None, None]],
        "actors": [["digger", None, None], [None, None, None]],
    })
    assert text.splitlines()[1:] == [
        "1#?",
        "???",
        "Target legend: ?=any (unconstrained), 1=Digger, #=rock",
        "Also required: (0,0) .=Cut floor",
    ], text


def test_anonymous_target_legend_lists_labels_only():
    game = _symbol_game()
    labels = build_anon_kind_to_label(game)
    text = _target_text({
        "ground": [["floor", None, None], [None, None, None]],
        "actors": [["digger", None, None], [None, None, "digger"]],
    }, anon=True)
    lines = text.splitlines()
    assert lines[1] == f"{labels['digger']}??", text
    assert lines[3] == f"Target legend: ?=any (unconstrained), {labels['digger']}", text
    # floor's symbol is "." so it has no alias and keeps its own symbol.
    assert "floor" not in labels
    assert lines[4] == "Also required: (0,0) .", text
    for leak in ("Cut floor", "Landed Pod", "Digger", "floor", "digger"):
        assert leak not in text, f"{leak!r} leaked into {text!r}"


# ── balance: connectivity ─────────────────────────────────────────────────

# Wei holds (0,0),(1,0) and a cut-off (0,2); Shu holds (2,1),(2,2); Wu none.
_CONNECTED = [(0, 0, "terr_wei"), (1, 0, "terr_wei"), (0, 2, "terr_wei"),
              (2, 1, "terr_shu"), (2, 2, "terr_shu")]


def _connected_goal() -> dict:
    return _goal(requireConnected=True, connectionSources={
        "terr_wei": [0, 0], "terr_shu": [2, 2], "terr_wu": [1, 1]})


def test_connected_balance_states_connectivity_and_counts():
    text = _render(_connected_goal(), territory=_CONNECTED)
    assert text == (
        "Claim every claimable cell, and give Wei territory, Shu territory and "
        "Wu territory an equal number each, and each owner's cells must connect "
        "orthogonally to its source cell [Wei territory (0,0), Shu territory (2,2), "
        "Wu territory (1,1)] (Wei territory 2/3 connected, Shu territory 2/2, "
        "Wu territory 0/0 — 5 of 9 claimed)"), text


def test_connected_balance_anonymous():
    labels = build_anon_kind_to_label(_make_game())
    w, s, u = labels["terr_wei"], labels["terr_shu"], labels["terr_wu"]
    text = _render(_connected_goal(), territory=_CONNECTED, anon=True)
    assert text.endswith(
        f"source cell [{w} (0,0), {s} (2,2), {u} (1,1)] "
        f"({w} 2/3 connected, {s} 2/2, {u} 0/0 — 5 of 9 claimed)"), text


def test_override_keeps_connected_progress():
    game = _make_game()
    game.goal_descriptions = {"balance_goal": "Split it; stay connected."}
    state = _make_state(game, _CONNECTED)
    text = render_goals(_connected_goal(), state, game)
    assert text == ("Split it; stay connected. (now: Wei territory 2/3 connected, "
                    "Shu territory 2/2, Wu territory 0/0 — 5 of 9 claimed)"), text


def test_override_on_a_goal_without_progress_is_unchanged():
    game = _make_game()
    game.goal_descriptions = {"match_goal": "Put Wei in the middle."}
    state = _make_state(game, _PARTIAL)
    assert render_goals(_board_match("terr_wei"), state, game) == "Put Wei in the middle."


def test_override_on_sequence_match_appends_done_count():
    game = _make_game()
    game.goal_descriptions = {"seq": "Merge 2, then 4."}
    state = _make_state(game, _PARTIAL)
    state.sequence_indices["seq"] = 1
    level = {"goals": [{"id": "seq", "type": "sequence_match",
                        "config": {"sequence": [2, 4]}}]}
    assert render_goals(level, state, game) == "Merge 2, then 4. (now: 1/2 done)"


# ── loss reasons ──────────────────────────────────────────────────────────

_LOSE_LEVEL = {"loseConditions": [
    {"type": "max_actions", "config": {"limit": 11}},
    {"type": "variable_threshold", "config": {"variable": "heat", "target": 3}},
    {"type": "balance_budget_exhausted", "config": {}},
    {"type": "balance_unreachable", "config": {}},
]}


def test_generic_loss_reasons():
    assert describe_loss(_LOSE_LEVEL, "max_actions") == "move limit of 11 reached"
    assert describe_loss(_LOSE_LEVEL, "variable_threshold:heat") == \
        'loss condition "heat" reached'
    assert describe_loss(_LOSE_LEVEL, "balance_budget_exhausted") == \
        "a piece's remaining moves can no longer complete its share"
    assert describe_loss(_LOSE_LEVEL, "balance_unreachable") == \
        "the balance goal became unreachable"


def test_anonymous_loss_reasons_hide_variable_names():
    assert describe_loss(_LOSE_LEVEL, "variable_threshold:heat", anonymize=True) == \
        'loss condition "#2" reached'
    assert describe_loss(_LOSE_LEVEL, "max_actions", anonymize=True) == \
        "move limit of 11 reached"


def test_lose_condition_description_wins_in_named_mode_only():
    level = {"loseConditions": [
        {"type": "variable_threshold", "config": {"variable": "heat", "target": 3},
         "description": "the boiler overheated"}]}
    assert describe_loss(level, "variable_threshold:heat") == "the boiler overheated"
    assert describe_loss(level, "variable_threshold:heat", anonymize=True) == \
        'loss condition "#1" reached'


# ── row/column 0 is a real index ──────────────────────────────────────────

def test_row_and_column_zero_are_not_rendered_as_unknown():
    for goal_type, extra in (("sum_constraint", {"target": 5}),
                             ("count_constraint", {"predicate": "even", "target": 1})):
        for scope, word in (("row", "row"), ("col", "column")):
            level = {"goals": [{"id": "c", "type": goal_type,
                                "config": {"scope": scope, "index": 0, **extra}}]}
            text = _render(level)
            assert f"{word} 0" in text and "?" not in text, text


def test_target_entry_with_params_renders_its_kind():
    """Entry-form target cells may carry params (e.g. `{"kind": "watcher"}`
    plus extra keys); the goal compares kinds only, so only the kind shows."""
    text = _target_text({"objects": [[{"kind": "pod", "facing": "up"}, None, None],
                                     [None, None, None]]})
    assert text.splitlines()[1:] == [
        "p??", "???", "Target legend: ?=any (unconstrained), p=Landed Pod"], text


# ── several goals ───────────────────────────────────────────────────────

def _multi_goal_text(goals: list[dict], *, anon: bool = False) -> str:
    game = _symbol_game()
    board = Board.from_json({"size": [3, 2], "layers": {}}, game.layers)
    state = GameState.from_json({}, board, game.defaults)
    labels = build_anon_kind_to_label(game) if anon else None
    return render_goals({"goals": goals}, state, game, anonymize=anon,
                        kind_to_label=labels)


_MATCH = {"id": "m", "type": "board_match", "config": {
    "targetLayers": {"objects": [["pod", None, None], [None, None, None]]}}}
_CLEAR = {"id": "c", "type": "all_cleared", "config": {"kind": "pod"}}
_REACH = {"id": "r", "type": "reach_target", "config": {"targetKind": "pod"}}


def test_a_goal_after_a_target_grid_starts_on_its_own_line():
    """It used to be appended to the target legend with "; ", so the next
    goal read as one more legend entry."""
    for anon in (False, True):
        lines = _multi_goal_text([_MATCH, _CLEAR], anon=anon).splitlines()
        assert lines[3].startswith("Target legend: ") and ";" not in lines[3], lines
        assert lines[4].startswith("Clear all "), lines
        assert len(lines) == 5, lines


def test_consecutive_target_grids_each_end_cleanly():
    lines = _multi_goal_text([_MATCH, _MATCH, _REACH]).splitlines()
    assert [i for i, l in enumerate(lines) if l.startswith("Arrange")] == [0, 4], lines
    assert lines[3].startswith("Target legend: ") and ";" not in lines[3], lines
    assert lines[7] == "Target legend: ?=any (unconstrained), p=Landed Pod", lines
    assert lines[8] == "Reach the Landed Pod", lines


def test_single_line_goals_still_join_with_semicolons():
    assert _multi_goal_text([_REACH, _CLEAR]) == (
        "Reach the Landed Pod; Clear all Landed Pods from the board")
    # A single-line goal before a grid keeps "; " (the grid follows its own
    # "match the target pattern:" line).
    assert _multi_goal_text([_REACH, _MATCH]).startswith(
        "Reach the Landed Pod; Arrange tiles to match the target pattern:\n")
    assert join_goal_parts([]) == "" and join_goal_parts(["a"]) == "a"
    assert join_goal_parts(["a\nb", "c", "d"]) == "a\nb\nc; d"


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
