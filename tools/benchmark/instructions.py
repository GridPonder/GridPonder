"""Compile the human-facing instruction stream for benchmark study levels."""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engines.python._turn_engine import TurnEngine
from engines.python.goal_renderer import render_goals
from engines.python.loader import load_pack


INSTRUCTION_POLICY = "authored-v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


@dataclass(frozen=True)
class StoryInstruction:
    sequence_index: int
    title: str
    text: str
    image: str | None


@dataclass(frozen=True)
class InstructionPayload:
    policy: str
    pack_id: str
    level_id: str
    level_index: int
    sequence_index: int
    stage_index: int
    game_title: str
    game_description: str
    stories: tuple[StoryInstruction, ...]
    level_title: str
    guide: str
    rendered_goal: str
    omitted_media: tuple[str, ...]
    source_files: tuple[str, ...]
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def supplemental_prompt(self) -> str:
        """Return context not already emitted by the standard game prompt."""
        sections: list[str] = []
        if self.stories:
            story_text = []
            for story in self.stories:
                heading = story.title or f"Story {story.sequence_index + 1}"
                story_text.append(f"[{heading}]\n{story.text}".strip())
            sections.append("AUTHORED GUIDANCE AVAILABLE BEFORE THIS LEVEL:\n" + "\n\n".join(story_text))
        if self.level_title:
            sections.append(f"CURRENT LEVEL TITLE: {self.level_title}")
        if self.guide:
            sections.append(f"CURRENT LEVEL GUIDE:\n{self.guide}")
        if not sections:
            return ""
        return "\n\n".join(sections)


def _payload_digest(data: dict[str, Any]) -> str:
    digest_data = dict(data)
    digest_data.pop("digest", None)
    return sha256_json(digest_data)


def compile_pack_instructions(
    packs_dir: Path,
    pack_id: str,
    *,
    policy: str = INSTRUCTION_POLICY,
) -> list[InstructionPayload]:
    if policy != INSTRUCTION_POLICY:
        raise ValueError(f"Unsupported instruction policy: {policy}")

    pack_dir = packs_dir / pack_id
    manifest_path = pack_dir / "manifest.json"
    game_path = pack_dir / "game.json"
    if not manifest_path.is_file() or not game_path.is_file():
        raise FileNotFoundError(f"Missing manifest.json or game.json for {pack_id}")

    manifest = json.loads(manifest_path.read_text())
    raw_game = json.loads(game_path.read_text())
    game_def, levels = load_pack(pack_dir)

    game_title = str(manifest.get("title") or pack_id)
    game_description = str(manifest.get("description") or "")
    prior_stories: list[StoryInstruction] = []
    payloads: list[InstructionPayload] = []
    level_index = 0

    for sequence_index, entry in enumerate(raw_game.get("levelSequence") or []):
        entry_type = entry.get("type")
        if entry_type == "story":
            prior_stories.append(
                StoryInstruction(
                    sequence_index=sequence_index,
                    title=str(entry.get("title") or ""),
                    text=str(entry.get("text") or ""),
                    image=str(entry["image"]) if entry.get("image") else None,
                )
            )
            continue
        if entry_type != "level" or not entry.get("ref"):
            continue

        level_id = str(entry["ref"])
        if level_id not in levels:
            raise ValueError(
                f"{pack_id}/game.json references missing level {level_id}"
            )
        level = levels[level_id]
        engine = TurnEngine(game_def, level)
        rendered_goal = render_goals(level, engine.state, game_def)
        level_path = pack_dir / "levels" / f"{level_id}.json"
        omitted_media = tuple(
            story.image for story in prior_stories if story.image
        )
        raw_payload: dict[str, Any] = {
            "policy": policy,
            "pack_id": pack_id,
            "level_id": level_id,
            "level_index": level_index,
            "sequence_index": sequence_index,
            "stage_index": len(prior_stories),
            "game_title": game_title,
            "game_description": game_description,
            "stories": tuple(prior_stories),
            "level_title": str(level.get("title") or level_id),
            "guide": str(level.get("guide") or ""),
            "rendered_goal": rendered_goal,
            "omitted_media": omitted_media,
            "source_files": (
                f"{pack_id}/manifest.json",
                f"{pack_id}/game.json",
                f"{pack_id}/levels/{level_id}.json",
            ),
        }
        serializable = {
            **raw_payload,
            "stories": [asdict(story) for story in prior_stories],
        }
        payloads.append(
            InstructionPayload(
                **raw_payload,
                digest=_payload_digest(serializable),
            )
        )
        level_index += 1

    return payloads


def compile_instruction_map(
    packs_dir: Path,
    pack_ids: Iterable[str],
    *,
    policy: str = INSTRUCTION_POLICY,
) -> dict[tuple[str, str], InstructionPayload]:
    compiled: dict[tuple[str, str], InstructionPayload] = {}
    for pack_id in pack_ids:
        for payload in compile_pack_instructions(
            packs_dir, pack_id, policy=policy
        ):
            compiled[(pack_id, payload.level_id)] = payload
    return compiled


def compose_study_prompt(
    base_prompt: str,
    instruction: InstructionPayload,
    notebook: str = "",
) -> str:
    """Compose a study prompt while keeping notebook absence byte-stable."""
    sections = [base_prompt.rstrip()]
    supplemental = instruction.supplemental_prompt
    if supplemental:
        sections.append(supplemental)
    notebook = notebook.strip()
    if notebook:
        sections.append(
            "CROSS-LEVEL GAME NOTEBOOK FROM EARLIER LEVELS:\n"
            + notebook
        )
    return "\n\n".join(sections) + "\n"


def audit_instruction_payloads(
    payloads: Iterable[InstructionPayload],
) -> dict[str, Any]:
    payload_list = list(payloads)
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    pack_stats: dict[str, dict[str, int]] = {}

    for payload in payload_list:
        stats = pack_stats.setdefault(
            payload.pack_id,
            {
                "levels": 0,
                "levels_with_stories": 0,
                "levels_with_guides": 0,
                "levels_with_omitted_media": 0,
                "max_preceding_stories": 0,
                "max_omitted_media": 0,
            },
        )
        stats["levels"] += 1
        stats["levels_with_stories"] += bool(payload.stories)
        stats["levels_with_guides"] += bool(payload.guide)
        stats["levels_with_omitted_media"] += bool(payload.omitted_media)
        stats["max_preceding_stories"] = max(
            stats["max_preceding_stories"], len(payload.stories)
        )
        stats["max_omitted_media"] = max(
            stats["max_omitted_media"], len(payload.omitted_media)
        )
        key = (payload.pack_id, payload.level_id)
        if key in seen:
            issues.append(
                {
                    "level": f"{payload.pack_id}/{payload.level_id}",
                    "message": "duplicate instruction payload",
                }
            )
        seen.add(key)
        if not payload.game_description:
            warnings.append(
                {
                    "level": f"{payload.pack_id}/{payload.level_id}",
                    "message": "game description is empty",
                }
            )
        if not payload.rendered_goal:
            issues.append(
                {
                    "level": f"{payload.pack_id}/{payload.level_id}",
                    "message": "rendered goal is empty",
                }
            )
    for pack_id, stats in sorted(pack_stats.items()):
        if stats["levels_with_omitted_media"]:
            warnings.append(
                {
                    "level": pack_id,
                    "message": (
                        f"story images precede "
                        f"{stats['levels_with_omitted_media']}/"
                        f"{stats['levels']} levels and are recorded but "
                        "omitted from the initial study "
                        f"(maximum {stats['max_omitted_media']} per level)"
                    ),
                }
            )

    return {
        "policy": INSTRUCTION_POLICY,
        "payload_count": len(payload_list),
        "pack_count": len({payload.pack_id for payload in payload_list}),
        "issues": issues,
        "warnings": warnings,
        "packs": pack_stats,
        "ok": not issues,
    }
