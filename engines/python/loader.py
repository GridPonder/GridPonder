"""
Pack loader: reads a pack directory and returns (GameDef, levels_dict).

Usage::

    from engines.python.loader import load_pack
    game, levels = load_pack('/path/to/packs/carrot_quest')
    engine = TurnEngine(game, levels['fw_001'])
"""
from __future__ import annotations
import json
from pathlib import Path
from ._game_def import GameDef
from ._turn_engine import TurnEngine


def load_pack(pack_dir: str | Path) -> tuple[GameDef, dict[str, dict]]:
    """
    Load a pack directory.

    Returns
    -------
    game : GameDef
        Parsed game.json + manifest metadata.
    levels : dict[str, dict]
        level_id → raw level JSON dict (not yet bound to a GameState).
        Pass a value to TurnEngine(game, levels['level_id']).
    """
    pack = Path(pack_dir)
    manifest = json.loads((pack / "manifest.json").read_text())
    game_json = json.loads((pack / "game.json").read_text())

    game = GameDef.from_dict(
        game_json,
        id=manifest.get("id", ""),
        title=manifest.get("title", ""),
        description=manifest.get("description", ""),
    )

    levels: dict[str, dict] = {}
    levels_dir = pack / "levels"
    if levels_dir.exists():
        for level_file in sorted(levels_dir.glob("*.json")):
            level_json = json.loads(level_file.read_text())
            level_id = level_json.get("id", level_file.stem)
            levels[level_id] = level_json

    return game, levels


def make_engine(pack_dir: str | Path, level_id: str) -> TurnEngine:
    """Convenience: load a pack and return a TurnEngine for one level."""
    game, levels = load_pack(pack_dir)
    if level_id not in levels:
        raise KeyError(f"Level '{level_id}' not found in {pack_dir}")
    return TurnEngine(game, levels[level_id])
