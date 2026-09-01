"""Game systems package — one submodule per system type.

Mirrors the layout of `engines/dart/lib/src/systems/`. Adding a new system
means dropping a new file here and adding it to `_REGISTRY` below.

Public API (re-exported for `from engines.python._systems import …`):
  - GameSystem            (base class)
  - instantiate_systems   (entry point used by the turn engine)
"""
from __future__ import annotations
from typing import Callable, Optional

from .._game_def import GameDef
from ._base import GameSystem
from .anchor_point import AnchorPointSystem
from .avatar_navigation import AvatarNavigationSystem
from .coupled_actors import CoupledActorsSystem
from .flank_capture import FlankCaptureSystem
from .flood_fill import FloodFillSystem
from .follower_npcs import FollowerNpcsSystem
from .ice_slide import IceSlideSystem
from .individual_actors import IndividualActorsSystem
from .line_of_sight import LineOfSightSystem
from .overlay_cursor import OverlayCursorSystem
from .portals import PortalsSystem
from .push_objects import PushObjectsSystem
from .queued_emitters import QueuedEmittersSystem
from .region_transform import RegionTransformSystem
from .sided_box import SidedBoxSystem
from .sliding_blocks import SlidingBlocksSystem
from .slide_merge import SlideMergeSystem
from .support_collapse import SupportCollapseSystem
from .sonar import SonarSystem
from .terrain_edit import TerrainEditSystem
from .terrain_skip import TerrainSkipSystem
from .tile_teleport import TileTeleportSystem


SystemFactory = Callable[[str, dict], GameSystem]

_REGISTRY: dict[str, SystemFactory] = {
    "anchor_point": lambda sys_id, _: AnchorPointSystem(sys_id),
    "avatar_navigation": lambda sys_id, _: AvatarNavigationSystem(sys_id),
    "push_objects": lambda sys_id, _: PushObjectsSystem(sys_id),
    "portals": lambda sys_id, _: PortalsSystem(sys_id),
    "ice_slide": lambda sys_id, _: IceSlideSystem(sys_id),
    "flood_fill": lambda sys_id, _: FloodFillSystem(sys_id),
    "slide_merge": lambda sys_id, _: SlideMergeSystem(sys_id),
    "overlay_cursor": lambda sys_id, _: OverlayCursorSystem(sys_id),
    "region_transform": lambda sys_id, _: RegionTransformSystem(sys_id),
    "queued_emitters": lambda sys_id, _: QueuedEmittersSystem(sys_id),
    "tile_teleport": lambda sys_id, _: TileTeleportSystem(sys_id),
    "sided_box": lambda sys_id, _: SidedBoxSystem(sys_id),
    "sliding_blocks": lambda sys_id, config: SlidingBlocksSystem(sys_id, config),
    "line_of_sight": lambda sys_id, config: LineOfSightSystem(sys_id, config),
    "flank_capture": lambda sys_id, config: FlankCaptureSystem(sys_id, config),
    "support_collapse": lambda sys_id, config: SupportCollapseSystem(sys_id, config),
    "sonar": lambda sys_id, _: SonarSystem(sys_id),
    "terrain_edit": lambda sys_id, _: TerrainEditSystem(sys_id),
    "follower_npcs": lambda sys_id, _: FollowerNpcsSystem(sys_id),
    "coupled_actors": lambda sys_id, _: CoupledActorsSystem(sys_id),
    "individual_actors": lambda sys_id, _: IndividualActorsSystem(sys_id),
    "terrain_skip": lambda sys_id, _: TerrainSkipSystem(sys_id),
}


def supported_system_types() -> frozenset[str]:
    return frozenset(_REGISTRY)


def unsupported_system_types(game: GameDef) -> list[str]:
    return sorted(
        {
            system["type"]
            for system in game.systems
            if system.get("enabled", True) and system["type"] not in _REGISTRY
        }
    )


def instantiate_systems(game: GameDef, overrides: Optional[dict] = None) -> list[GameSystem]:
    effective_game = game.with_system_overrides(overrides)
    unsupported = unsupported_system_types(effective_game)
    if unsupported:
        raise ValueError(
            "Unsupported enabled game system type(s): " + ", ".join(unsupported)
        )
    systems = []
    for sys_def in effective_game.systems:
        if not sys_def.get("enabled", True):
            continue
        factory = _REGISTRY[sys_def["type"]]
        config = effective_game.system_config(sys_def["id"])
        systems.append(factory(sys_def["id"], config))
    return systems


__all__ = [
    "GameSystem",
    "instantiate_systems",
    "supported_system_types",
    "unsupported_system_types",
]
