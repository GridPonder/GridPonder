from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from run_manifest import pack_inventory, packs_digest


def _write_pack(
    root: Path,
    pack_id: str,
    payload: str,
    tags: list[str] | None = None,
) -> None:
    pack = root / pack_id
    pack.mkdir()
    (pack / "manifest.json").write_text(
        json.dumps(
            {
                "id": pack_id,
                "title": pack_id,
                "tags": tags or ["spatial-planning"],
            }
        )
    )
    (pack / "game.json").write_text(
        json.dumps(
            {
                "levelSequence": [
                    {"type": "level", "ref": f"{pack_id}_001"},
                ]
            }
        )
    )
    (pack / "payload.txt").write_text(payload)


def test_excluded_packs_are_omitted_from_inventory_and_digest() -> None:
    with TemporaryDirectory() as temp:
        root = Path(temp)
        _write_pack(root, "production", "stable")
        _write_pack(root, "fixture", "version-one")
        (root / "README.md").write_text("not pack data")

        inventory = pack_inventory(root, {"fixture"})
        digest = packs_digest(root, {"fixture"})
        assert list(inventory) == ["production"]
        assert inventory["production"]["tags"] == ["spatial-planning"]

        (root / "fixture" / "payload.txt").write_text("version-two")
        (root / "README.md").write_text("also not pack data")
        assert packs_digest(root, {"fixture"}) == digest

        (root / "production" / "payload.txt").write_text("changed")
        assert packs_digest(root, {"fixture"}) != digest


if __name__ == "__main__":
    test_excluded_packs_are_omitted_from_inventory_and_digest()
    print("1 passed")
