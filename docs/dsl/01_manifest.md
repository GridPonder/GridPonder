# Gridponder DSL — Manifest Schema

The pack's entry point: declares identity, version, compatibility requirements, and presentation metadata without loading any gameplay content.

## Purpose

`manifest.json` is the entry point of a game pack. It declares pack identity, versioning, compatibility requirements, and presentation metadata (title, description, cover art). The platform app reads the manifest to display the pack in the library without loading the full game definition.

`manifest.json` does **not** contain gameplay content. The level sequence, entity definitions, systems, and rules all live in `game.json`.

---

## Schema

```json
{
  "dslVersion": "0.5",
  "packVersion": 1,
  "gameId": "com.example.mygame",
  "title": "My Puzzle Game",
  "shortDescription": "One-line tagline for the home screen.",
  "description": "A full mechanical description used by the LLM-prompt header and detail views — names every entity and explains how the rules work.",
  "coverImage": "assets/cover.png",
  "version": "1.0.0",
  "minEngineVersion": "0.5.0",
  "author": "Author Name",
  "license": "CC-BY-4.0",
  "website": "https://example.com"
}
```

---

## Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `dslVersion` | string | **yes** | DSL version this pack uses. Semantic versioning. |
| `packVersion` | integer | **yes** | Internal pack format version (currently `1`). |
| `gameId` | string | **yes** | Globally unique game identifier. Reverse-domain recommended: `com.author.gamename`. |
| `title` | string | **yes** | Human-readable game title. |
| `version` | string | **yes** | Game content version. Semantic versioning. |
| `author` | string | no | Author or team name. |
| `shortDescription` | string | no | One-sentence tagline used by the home screen / library tile. Should be self-contained and visually compact (under ~80 chars). |
| `description` | string | no | Full mechanical description (paragraph). Names every entity by its display word and explains how the rules work. Consumed by the LLM-prompt header and by detail views. Falls back to `shortDescription` when absent. |
| `minEngineVersion` | string | **yes** | Minimum engine version required to run this pack. |
| `gameFile` | string | no | Path to the game definition file. Default: `"game.json"`. |
| `levelDirectory` | string | no | Directory containing level files. Default: `"levels"`. |
| `assetsDirectory` | string | no | Directory containing assets. Default: `"assets"`. |
| `coverImage` | string | no | Path to cover art image (relative to pack root). |
| `license` | string | no | SPDX license identifier or `"proprietary"`. |
| `website` | string | no | URL for more information. |
| `sharedAssets` | array of strings | no | Shared asset collection IDs this pack depends on. See [Shared Assets](#shared-assets). |

---

## Shared Assets

Games may reference **shared asset collections** managed by the platform rather than bundling every asset inside the pack. This avoids duplicating common sprites (e.g., the standard rabbit avatar) across many games.

```json
{
  "sharedAssets": ["gridponder-base", "rabbit-character"]
}
```

A shared asset collection is a named folder in the platform's shared asset store. When a game references a shared collection, the engine resolves asset paths by checking:

1. The pack's own `assets/` directory first (local always wins)
2. Each shared collection in declaration order

### Resolution rules

- A pack that uses `sharedAssets` can reference sprites from those collections as if they were local (e.g., `"assets/sprites/avatar/rabbit_looking_right.png"` could come from the `rabbit-character` collection).
- At import time, the platform verifies that all declared shared collections are available. Import fails with a clear message if a collection is missing.
- For **portable distribution** (sharing a pack as a zip), the pack can be **flattened** — tooling copies all referenced shared assets into the pack folder so it becomes fully self-contained.

### When to use shared assets

| Scenario | Recommendation |
|----------|---------------|
| Flagship games sharing the standard rabbit | Use `sharedAssets: ["rabbit-character"]` |
| Community game with custom art | Don't use shared assets — bundle everything |
| Game reusing common tiles (walls, water, etc.) | Use `sharedAssets: ["gridponder-base"]` |

Shared asset collections are managed by the platform and can be updated independently of game packs.

---

## Validation Rules

1. `dslVersion` must be a recognized version supported by the engine.
2. `gameId` must be non-empty and use only alphanumeric characters, dots, hyphens, and underscores.
3. `gameFile` must point to an existing JSON file in the pack.
4. `minEngineVersion` is compared against the running engine version; import fails if the engine is too old.
5. `version` should follow semantic versioning (`major.minor.patch`).

---

## Compatibility

When the engine version is lower than `minEngineVersion`, the platform must:
- Refuse to import the pack
- Display a clear message indicating the required engine version
- Not attempt partial loading
