"""Game systems package — one submodule per system type.

Mirrors the layout of `engines/dart/lib/src/systems/`. Adding a new system
means dropping a new file here and adding it to `_REGISTRY` below.

Public API (re-exported for `from engines.python._systems import …`):
  - GameSystem            (base class)
  - instantiate_systems   (entry point used by the turn engine)
"""
from __future__ import annotations
from typing import Optional

from .._game_def import GameDef
from ._base import GameSystem
from .anchor_point import AnchorPointSystem
from .avatar_navigation import AvatarNavigationSystem
from .flood_fill import FloodFillSystem
from .follower_npcs import FollowerNpcsSystem
from .ice_slide import IceSlideSystem
from .overlay_cursor import OverlayCursorSystem
from .portals import PortalsSystem
from .push_objects import PushObjectsSystem
from .queued_emitters import QueuedEmittersSystem
from .region_transform import RegionTransformSystem
from .sided_box import SidedBoxSystem
from .slide_merge import SlideMergeSystem
from .tile_teleport import TileTeleportSystem


_REGISTRY: dict[str, type[GameSystem]] = {
    "anchor_point":      AnchorPointSystem,
    "avatar_navigation": AvatarNavigationSystem,
    "push_objects":      PushObjectsSystem,
    "portals":           PortalsSystem,
    "ice_slide":         IceSlideSystem,
    "flood_fill":        FloodFillSystem,
    "slide_merge":       SlideMergeSystem,
    "overlay_cursor":    OverlayCursorSystem,
    "region_transform":  RegionTransformSystem,
    "queued_emitters":   QueuedEmittersSystem,
    "tile_teleport":     TileTeleportSystem,
    "sided_box":         SidedBoxSystem,
    "follower_npcs":     FollowerNpcsSystem,
}


def instantiate_systems(game: GameDef, overrides: Optional[dict] = None) -> list[GameSystem]:
    systems = []
    for sys_def in game.systems:
        if not sys_def.get("enabled", True):
            continue
        cls = _REGISTRY.get(sys_def["type"])
        if cls is not None:
            systems.append(cls(sys_def["id"]))
    return systems


__all__ = ["GameSystem", "instantiate_systems"]
