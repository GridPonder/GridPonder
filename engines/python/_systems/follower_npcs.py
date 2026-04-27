"""FollowerNpcsSystem — see docs/dsl/04_systems.md."""
from __future__ import annotations
from collections import deque
from typing import Any, Optional

from .._models import (
    Pos, Entity, GameState, PendingMove, OverlayCursor,
    dir_delta, dir_opposite, is_cardinal, CARDINALS,
)
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem


class FollowerNpcsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "follower_npcs")

