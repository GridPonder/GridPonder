"""Board image renderer: theme palette colours, declared layer order, the
selected-piece ring, the overlay frame and hidden-item insets.

Builds a throwaway pack (no sprites, `display` blocks only) and renders it.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent.parent
for p in (str(REPO_ROOT), str(BENCH_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from board_image import AXIS_PX, CELL_PX, PADDING, render_board_image  # noqa: E402
from engines.python._models import OverlayCursor  # noqa: E402
from engines.python._turn_engine import TurnEngine  # noqa: E402
from engines.python.loader import load_pack  # noqa: E402

_PALETTE = {"team_tint": "#123456", "gold": "#abcdef", "special": "#fedcba"}

_GAME = {
    "layers": [
        {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
        # Declared order puts `upper` above `lower` even though neither is a
        # layer name the renderer knows.
        {"id": "lower", "occupancy": "zero_or_one"},
        {"id": "upper", "occupancy": "zero_or_one"},
        {"id": "actors", "occupancy": "zero_or_one"},
    ],
    "entityKinds": {
        "empty": {"layer": "ground", "symbol": ".", "display": {"type": "fill", "color": "white"}},
        "special": {"layer": "ground", "symbol": "S",
                    "display": {"type": "fill", "color": "special"}},
        "tint": {"layer": "lower", "symbol": "t", "display": {"type": "fill", "color": "team_tint"}},
        "cover": {"layer": "upper", "symbol": "c", "display": {"type": "fill", "color": "gold"}},
        "piece": {"layer": "actors", "symbol": "P", "tags": ["actor"], "uiName": "Piece",
                  "display": {"type": "circle", "color": "red"}},
    },
    "actions": [
        {"id": "move", "params": {"direction": {"type": "direction",
                                                "values": ["up", "down", "left", "right"]}}},
        {"id": "tap_cell", "params": {"position": {"type": "position"}}},
    ],
    "systems": [
        {"id": "individual", "type": "individual_actors",
         "config": {"actorLayer": "actors", "groundLayer": "ground"}},
    ],
    "defaults": {"avatar": {"enabled": False}},
}


def _level() -> dict:
    return {
        "id": "bi_01",
        "board": {"size": [4, 1], "layers": {
            "ground": {"format": "sparse", "entries": [{"position": [2, 0], "kind": "special"}]},
            # (0,0): tint only.  (1,0): tint under cover.  (2,0): special
            # ground under a full tint fill.  (3,0): a piece.
            "lower": {"format": "sparse", "entries": [
                {"position": [0, 0], "kind": "tint"},
                {"position": [1, 0], "kind": "tint"},
                {"position": [2, 0], "kind": "tint"},
            ]},
            "upper": {"format": "sparse", "entries": [{"position": [1, 0], "kind": "cover"}]},
            "actors": {"format": "sparse", "entries": [{"position": [3, 0], "kind": "piece"}]},
        }},
        "state": {"avatar": {"enabled": False}},
        "goals": [{"id": "g", "type": "reach_target", "config": {"targetKind": "special"}}],
        "solution": {"goldPath": [{"action": "tap_cell", "position": [3, 0]}]},
    }


def _render(mutate=None):
    with tempfile.TemporaryDirectory() as tmp:
        pack = Path(tmp) / "bipack"
        (pack / "levels").mkdir(parents=True)
        (pack / "manifest.json").write_text(json.dumps({"id": "bipack", "title": "BI"}))
        (pack / "game.json").write_text(json.dumps(_GAME))
        (pack / "theme.json").write_text(json.dumps({"palette": _PALETTE}))
        (pack / "levels" / "bi_01.json").write_text(json.dumps(_level()))
        game_def, levels = load_pack(pack)
        level = levels["bi_01"]
        engine = TurnEngine(game_def, level)
        if mutate is not None:
            mutate(engine)
        png, marks = render_board_image(game_def, engine.state, pack, level)
    return Image.open(io.BytesIO(png)).convert("RGB"), marks


def _px(img, x, y, dx=CELL_PX // 2, dy=CELL_PX // 2):
    return img.getpixel((AXIS_PX + PADDING + x * CELL_PX + dx, AXIS_PX + PADDING + y * CELL_PX + dy))


def _hex(value: str):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def test_display_colours_resolve_through_the_theme_palette():
    img, _ = _render()
    assert _px(img, 0, 0) == _hex(_PALETTE["team_tint"])


def test_layers_draw_in_declared_order():
    img, _ = _render()
    # `upper` is declared after `lower`, so the cover hides the tint.
    assert _px(img, 1, 0) == _hex(_PALETTE["gold"])


def test_hidden_item_gets_an_inset_and_is_reported():
    img, marks = _render()
    assert "hidden" in marks
    # (2,0): the special floor is fully covered by the tint; its inset sits
    # in the lower-left corner. (1,0): the tint under the cover is inset too.
    assert _px(img, 2, 0, dx=10, dy=CELL_PX - 12) == _hex(_PALETTE["special"])
    assert _px(img, 1, 0, dx=10, dy=CELL_PX - 12) == _hex(_PALETTE["team_tint"])
    # (0,0): the tint covers only the default floor, which is never inset.
    assert _px(img, 0, 0, dx=10, dy=CELL_PX - 12) == _hex(_PALETTE["team_tint"])


def test_selected_piece_ring_follows_the_selection_variables():
    _, marks = _render()
    assert "selected" not in marks

    def select(engine):
        assert engine.execute_turn("tap_cell", {"position": [3, 0]}).accepted

    img, marks = _render(select)
    assert "selected" in marks
    assert _px(img, 3, 0, dx=4, dy=CELL_PX // 2) == (255, 212, 90)

    def stale(engine):
        engine.state.variables["selectedActorKind"] = "piece"
        engine.state.variables["selectedActorPosition"] = [0, 0]  # no piece there

    _, marks = _render(stale)
    assert "selected" not in marks


def test_overlay_frame_is_drawn_and_reported():
    def overlay(engine):
        engine.state.overlay = OverlayCursor(0, 0, 2, 1)

    img, marks = _render(overlay)
    assert "overlay" in marks
    assert _px(img, 0, 0, dx=3, dy=CELL_PX // 2) == (255, 179, 0)


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as exc:
                failed += 1
                print(f"  FAIL  {name}: {exc}")
    sys.exit(1 if failed else 0)
