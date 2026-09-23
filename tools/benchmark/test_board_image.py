"""Regression tests for benchmark board-image observation visibility."""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine
from tools.benchmark.board_image import AXIS_PX, CELL_PX, PADDING, render_board_png


def _make_engine() -> tuple[GameDef, TurnEngine]:
    game = GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {
                    "layer": "ground",
                    "symbol": ".",
                    "display": {"type": "fill", "color": "green"},
                },
                "parking": {
                    "layer": "ground",
                    "symbol": ":",
                    "display": {"type": "fill", "color": "pink"},
                },
                "key": {
                    "layer": "objects",
                    "symbol": "K",
                    "display": {"type": "fill", "color": "yellow"},
                },
                "slab": {
                    "layer": "structures",
                    "tags": ["observation_occluder", "public_piece"],
                    "symbol": "B",
                    "display": {"type": "fill", "color": "blue"},
                },
            },
        }
    )
    level = {
        "board": {
            "size": [2, 1],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [{"position": [0, 0], "kind": "parking"}],
                },
                "objects": {
                    "format": "sparse",
                    "entries": [{"position": [0, 0], "kind": "key"}],
                },
            },
            "multiCellObjects": [
                {"id": "secret_key_cover", "kind": "slab", "cells": [[0, 0]]}
            ],
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }
    return game, TurnEngine(game, level)


def _cell_center(png: bytes, x: int, y: int) -> tuple[int, int, int]:
    image = Image.open(io.BytesIO(png)).convert("RGB")
    px = AXIS_PX + PADDING + x * CELL_PX + CELL_PX // 2
    py = AXIS_PX + PADDING + y * CELL_PX + CELL_PX // 2
    return image.getpixel((px, py))


class BoardImageVisibilityTest(unittest.TestCase):
    def test_occluder_hides_then_reveals_and_collected_key_stays_absent(self) -> None:
        game, engine = _make_engine()
        pack_dir = ROOT / "tools" / "benchmark" / "_no_pack_assets"

        concealed = render_board_png(game, engine.state, pack_dir)
        self.assertEqual(_cell_center(concealed, 0, 0), (37, 99, 235))
        engine.state.board.set_entity("objects", Pos(0, 0), None)
        concealed_without_key = render_board_png(game, engine.state, pack_dir)
        self.assertEqual(concealed_without_key, concealed)

        game, engine = _make_engine()
        engine.state.board.multi_cell_objects[0].cells = [Pos(1, 0)]
        revealed = render_board_png(game, engine.state, pack_dir)
        self.assertEqual(_cell_center(revealed, 0, 0), (234, 179, 8))

        engine.state.board.set_entity("objects", Pos(0, 0), None)
        collected = render_board_png(game, engine.state, pack_dir)
        self.assertEqual(_cell_center(collected, 0, 0), (236, 72, 153))
