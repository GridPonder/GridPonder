"""
GameDef: parsed game.json.

Mirrors Dart's GameDefinition, LayerDef, EntityKindDef, ActionDef, SystemDef,
RuleDef — but as plain Python dicts/dataclasses for simplicity.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def _parse_condition(j: dict | None):
    """Lazy import to avoid circular — conditions are parsed at rule-match time."""
    return j  # store raw dict; condition.py evaluates it


def _parse_effect(j: dict):
    return j  # store raw dict; effect.py executes it


# ---------------------------------------------------------------------------
# GameDef
# ---------------------------------------------------------------------------

class GameDef:
    """
    Parsed game.json.  All fields match the DSL schema in docs/dsl/02_game.md.
    """

    def __init__(self, data: dict, id: str = "", title: str = "", description: str = ""):
        self.id = id
        self.title = title
        self.description = description

        # Layers: list of {id, occupancy, isExactlyOne, defaultKind}
        self.layers: list[dict] = [
            {
                "id": ld["id"],
                "occupancy": ld.get("occupancy", "zero_or_one"),
                "isExactlyOne": ld.get("occupancy") == "exactly_one",
                "defaultKind": ld.get("default"),
            }
            for ld in data.get("layers", [])
        ]

        # Entity kinds: {kind_id: {id, layer, tags, params, animations, symbol, ...}}
        raw_kinds = data.get("entityKinds", {})
        self.entity_kinds: dict[str, dict] = {
            k: self._parse_kind(k, v) for k, v in raw_kinds.items()
        }

        # Actions: list of {id, params: {name: {type, values}}, entityKind?}
        self.actions: list[dict] = [
            {
                "id": a["id"],
                "params": a.get("params", {}),
                "entityKind": a.get("entityKind"),
            }
            for a in data.get("actions", [])
        ]

        # Systems: list of {id, type, config, enabled}
        self.systems: list[dict] = [
            {
                "id": s["id"],
                "type": s["type"],
                "config": s.get("config", {}),
                "enabled": s.get("enabled", True),
            }
            for s in data.get("systems", [])
        ]

        # Rules: list of rule dicts (raw — evaluated lazily)
        self.rules: list[dict] = [
            {
                "id": r["id"],
                "on": r["on"],
                "where": r.get("where"),
                "if": r.get("if"),
                "then": r.get("then", []),
                "priority": r.get("priority", 0),
                "once": r.get("once", False),
            }
            for r in data.get("rules", [])
        ]

        # Defaults
        raw_defaults = data.get("defaults", {})
        raw_avatar = raw_defaults.get("avatar", {})
        self.defaults = {
            "avatarEnabled": raw_avatar.get("enabled", True),
            "avatarFacing": raw_avatar.get("facing", "right"),
            "maxCascadeDepth": raw_defaults.get("maxCascadeDepth", 3),
        }

    @staticmethod
    def _parse_kind(kind_id: str, j: dict) -> dict:
        return {
            "id": kind_id,
            "layer": j.get("layer", "objects"),
            "tags": j.get("tags", []),
            "params": j.get("params", {}),
            "animations": j.get("animations", {}),
            "symbol": j.get("symbol", "?"),
            "symbolParam": j.get("symbolParam"),
            "sprite": j.get("sprite"),
            "spriteParam": j.get("spriteParam"),
            "uiName": j.get("uiName"),
            "description": j.get("description"),
        }

    def has_tag(self, kind_name: str, tag: str) -> bool:
        kind = self.entity_kinds.get(kind_name)
        return tag in (kind.get("tags", []) if kind else [])

    def system_config(self, system_id: str, overrides: Optional[dict] = None) -> dict:
        for s in self.systems:
            if s["id"] == system_id:
                base = s.get("config", {})
                if overrides and system_id in overrides:
                    return {**base, **overrides[system_id]}
                return base
        return {}

    def get_system_by_type(self, sys_type: str) -> Optional[dict]:
        for s in self.systems:
            if s["type"] == sys_type:
                return s
        return None

    def is_valid_action(self, action_id: str) -> bool:
        return any(a["id"] == action_id for a in self.actions)

    @classmethod
    def from_file(cls, game_json_path: str, id: str = "", title: str = "", description: str = "") -> "GameDef":
        data = json.loads(Path(game_json_path).read_text())
        return cls(data, id=id, title=title, description=description)

    @classmethod
    def from_dict(cls, data: dict, id: str = "", title: str = "", description: str = "") -> "GameDef":
        return cls(data, id=id, title=title, description=description)
