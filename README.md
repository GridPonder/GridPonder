# GridPonder

A lightweight puzzle game platform built around a data-driven game engine and a declarative DSL. Creators define games as structured data and assets — no custom code required. The engine interprets and runs any conforming game pack.

## Repository structure

```
app/        Flutter app (iOS, Android, macOS) — the player-facing shell
engines/    Engine implementations — engines/dart/ (Dart, used by app) and engines/python/ (Python, used by solver/benchmark)
packs/      Game packs defined in the GridPonder DSL
docs/       DSL specification and platform overview
tools/      Asset generation tooling (tile-gen via SDXL-Turbo)
.claude/    Claude Code skills for game and level authoring
```

## Game packs

| Pack | Levels | Mechanic |
|------|--------|----------|
| Carrot Quest | 8 | Avatar navigation, portals, pushing |
| Number Crunch | 5 | Slide and merge |
| Rotate & Flip | 2 | Overlay region transforms |
| Diagonal Swipes | 2 | Overlay diagonal swaps |
| Flood Colors | 1 | Flood fill |

Base tile sprites and character sprites live in `packs/gridponder-base/` and `packs/rabbit-character/` respectively and are shared across packs.

## Documentation

- [`docs/gridponder_platform_overview.md`](docs/gridponder_platform_overview.md) — architecture and design principles
- [`docs/dsl/`](docs/dsl/) — full DSL v0 specification (7 documents)

## Creator tooling

Three Claude Code skills are available for game authoring:

- `/revise-level` — analyse and redesign a level
- `/test-level` — run a level's gold path with screenshots
- `/tile-gen` — generate pixel-art tiles using local AI (SDXL-Turbo, MPS)
