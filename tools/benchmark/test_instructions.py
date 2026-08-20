from __future__ import annotations

import json
from pathlib import Path

from instructions import (
    compile_pack_instructions,
    compose_study_prompt,
)


PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"


def test_future_story_is_not_visible_early() -> None:
    payloads = compile_pack_instructions(PACKS_DIR, "carrot_quest")
    early = next(payload for payload in payloads if payload.level_id == "fw_001")
    late = next(payload for payload in payloads if payload.level_id == "fw_ice_002")

    assert [story.title for story in early.stories] == [
        "The Great Carrot Shortage"
    ]
    assert [story.title for story in late.stories] == [
        "The Great Carrot Shortage",
        "A Frosty Frontier",
    ]
    assert "A Frosty Frontier" not in early.supplemental_prompt


def test_hidden_level_metadata_is_not_in_instruction_payload() -> None:
    payloads = compile_pack_instructions(PACKS_DIR, "flood_colors")
    payload = next(item for item in payloads if item.level_id == "fl_009")
    raw_level = json.loads(
        (PACKS_DIR / "flood_colors" / "levels" / "fl_009.json").read_text()
    )
    hidden_description = raw_level["metadata"]["description"]

    assert hidden_description not in json.dumps(payload.to_dict())
    assert all(not path.startswith("/") for path in payload.source_files)


def test_empty_curriculum_notebook_is_prompt_identical() -> None:
    payload = compile_pack_instructions(PACKS_DIR, "number_cells")[0]
    base = "BASE PROMPT\n"

    independent = compose_study_prompt(base, payload, "")
    curriculum_first_level = compose_study_prompt(base, payload, "  ")
    learned = compose_study_prompt(base, payload, "Tiles merge once per move.")

    assert independent == curriculum_first_level
    assert learned.startswith(independent.rstrip())
    assert "CROSS-LEVEL GAME NOTEBOOK" in learned


def test_story_images_are_recorded_but_not_embedded() -> None:
    payload = compile_pack_instructions(PACKS_DIR, "number_cells")[0]

    assert payload.omitted_media == ("assets/number_cells.png",)
    assert "assets/number_cells.png" not in payload.supplemental_prompt


if __name__ == "__main__":
    test_future_story_is_not_visible_early()
    test_hidden_level_metadata_is_not_in_instruction_payload()
    test_empty_curriculum_notebook_is_prompt_identical()
    test_story_images_are_recorded_but_not_embedded()
    print("4 passed")
