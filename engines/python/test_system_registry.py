from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._systems import instantiate_systems, unsupported_system_types


def test_unknown_enabled_system_is_rejected() -> None:
    game = GameDef.from_dict(
        {
            "layers": [],
            "entityKinds": {},
            "actions": [],
            "systems": [{"id": "unknown", "type": "not_implemented"}],
        }
    )

    assert unsupported_system_types(game) == ["not_implemented"]
    try:
        instantiate_systems(game)
    except ValueError as exc:
        assert "not_implemented" in str(exc)
    else:
        raise AssertionError("unknown system was silently ignored")


def test_unknown_disabled_system_is_allowed() -> None:
    game = GameDef.from_dict(
        {
            "layers": [],
            "entityKinds": {},
            "actions": [],
            "systems": [
                {"id": "future", "type": "not_implemented", "enabled": False}
            ],
        }
    )

    assert unsupported_system_types(game) == []
    assert instantiate_systems(game) == []


if __name__ == "__main__":
    test_unknown_enabled_system_is_rejected()
    test_unknown_disabled_system_is_allowed()
    print("2 passed")
