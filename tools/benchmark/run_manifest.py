"""Reproducibility metadata for benchmark runs."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def source_snapshot(
    repo_root: Path,
    packs_dir: Path,
    excluded_packs: Iterable[str] = (),
) -> dict[str, Any]:
    excluded = frozenset(excluded_packs)
    snapshot = {
        "repository": _git_snapshot(repo_root),
        "packs_dir": str(packs_dir.resolve()),
        "excluded_packs": sorted(excluded),
        "packs_digest": packs_digest(packs_dir, excluded),
        "packs": pack_inventory(packs_dir, excluded),
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
        },
    }
    packs_repo_root = _git_root(packs_dir)
    if packs_repo_root and packs_repo_root != repo_root.resolve():
        snapshot["packs_repository"] = _git_snapshot(packs_repo_root)
    return snapshot


def pack_inventory(
    packs_dir: Path,
    excluded_packs: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    excluded = frozenset(excluded_packs)
    inventory: dict[str, dict[str, Any]] = {}
    if not packs_dir.is_dir():
        return inventory
    for pack_dir in sorted(packs_dir.iterdir()):
        if pack_dir.name in excluded:
            continue
        manifest_path = pack_dir / "manifest.json"
        game_path = pack_dir / "game.json"
        if not pack_dir.is_dir() or not manifest_path.is_file() or not game_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text())
            game = json.loads(game_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        level_ids = [
            entry["ref"]
            for entry in game.get("levelSequence", [])
            if entry.get("type") == "level" and entry.get("ref")
        ]
        inventory[pack_dir.name] = {
            "id": manifest.get("id", pack_dir.name),
            "title": manifest.get("title", pack_dir.name),
            "levels": level_ids,
            "level_count": len(level_ids),
        }
    return inventory


def packs_digest(
    packs_dir: Path,
    excluded_packs: Iterable[str] = (),
) -> str:
    digest = hashlib.sha256()
    if not packs_dir.is_dir():
        return ""
    excluded = frozenset(excluded_packs)
    pack_dirs = [
        path
        for path in sorted(packs_dir.iterdir())
        if path.is_dir()
        and path.name not in excluded
        and (path / "manifest.json").is_file()
        and (path / "game.json").is_file()
    ]
    included = 0
    for pack_dir in pack_dirs:
        for path in sorted(pack_dir.rglob("*")):
            if not path.is_file() or _ignored_pack_path(path.relative_to(packs_dir)):
                continue
            relative = path.relative_to(packs_dir).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
            included += 1
    return f"sha256:{digest.hexdigest()}:{included}"


def _ignored_pack_path(relative: Path) -> bool:
    return any(part in {".DS_Store", "__pycache__"} for part in relative.parts)


def _git_root(path: Path) -> Path | None:
    if not path.is_dir():
        return None
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def _git_snapshot(repo_root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    sha = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {
        "sha": sha,
        "dirty": bool(status),
        "branch": run("branch", "--show-current"),
    }
