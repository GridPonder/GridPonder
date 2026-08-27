"""Validation helpers for game-level benchmark tags."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


TAG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_GAME_TAGS = 12
MAX_TAG_LENGTH = 48


def validate_game_tags(
    manifest: dict[str, Any],
    *,
    pack_id: str,
    required: bool = False,
    allowed_tags: Iterable[str] | None = None,
) -> tuple[str, ...]:
    raw = manifest.get("tags", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list) or any(not isinstance(tag, str) for tag in raw):
        raise ValueError(f"{pack_id}: manifest.tags must be an array of strings")

    tags = tuple(raw)
    if required and not tags:
        raise ValueError(f"{pack_id}: manifest.tags must not be empty")
    if len(tags) > MAX_GAME_TAGS:
        raise ValueError(
            f"{pack_id}: manifest.tags has {len(tags)} values; "
            f"maximum is {MAX_GAME_TAGS}"
        )
    if len(set(tags)) != len(tags):
        raise ValueError(f"{pack_id}: manifest.tags contains duplicates")

    invalid = [
        tag
        for tag in tags
        if len(tag) > MAX_TAG_LENGTH or not TAG_PATTERN.fullmatch(tag)
    ]
    if invalid:
        raise ValueError(
            f"{pack_id}: invalid game tags {invalid}; use lowercase kebab-case "
            f"with at most {MAX_TAG_LENGTH} characters"
        )

    if allowed_tags is not None:
        allowed = frozenset(allowed_tags)
        unknown = sorted(set(tags) - allowed)
        if unknown:
            raise ValueError(
                f"{pack_id}: game tags are absent from the frozen taxonomy: "
                + ", ".join(unknown)
            )
    return tags
