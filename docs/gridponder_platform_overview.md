# Gridponder Platform Overview

## Purpose

This document defines the overall idea for **Gridponder as a medium/platform for mini puzzle games**.&#x20;

This round focuses on the **big picture**:

- the product vision
- the major system components
- how those components fit together
- the boundaries between the DSL, game packs, engine, and platform app
- what should be built first versus later

The DSL v0 formal specification has been completed and lives in `docs/dsl/` (7 documents covering overview, manifest, game definition, levels, systems, rules, and theme/controls).

---

## 1. Core Idea

Gridponder is not just a single puzzle game. It is a **lightweight puzzle medium** centered around elegant, intellectually satisfying, phone-friendly grid games.

A player installs the Gridponder app and gets:

- a curated set of polished built-in games
- a consistent platform experience for browsing, playing, and managing games
- the ability to import additional games shared by others

A creator uses the Gridponder DSL and tooling to define a game as **data plus assets**, not executable code. That game can then be packaged, shared, imported, and played by the Gridponder app.

In other words:

- **Gridponder Platform App** = the player-facing shell
- **Gridponder Engine** = the fixed runtime that interprets games
- **Gridponder DSL** = the constrained specification language for games and levels
- **Gridponder Game Pack** = a shareable folder/archive containing a game defined in the DSL plus assets and metadata

The design goal is to find the right balance between:

- simplicity and elegance
- enough expressive power for creative puzzle design
- strong mobile usability while also being web-friendly
- easy community contribution
- no server-side burden in the first versions (will only be considered if the platform gets traction)

---

## 2. Product Thesis

Gridponder should become a **playable reasoning medium**:

- intellectually satisfying like strong puzzle games
- structured enough for analysis, hints, and AI-assisted authoring
- constrained enough to be shareable and safe on app stores
- open enough that creators can build meaningful games&#x20;

The project should support three kinds of value simultaneously:

### 2.1 Player value

Players get elegant mobile puzzle experiences with:

- quick onboarding
- intuitive controls
- strong aha moments when solving a level
- replayable mini games
- clear progression
- lightweight (but not ugly) presentation

### 2.2 Creator value

Creators get a constrained but expressive medium for building:

- mini puzzle games
- themed worlds
- curated level progressions
- new mechanics assembled from a common runtime

Creators should not need to build an app, backend, or custom engine.

### 2.3 Long-term platform value

Gridponder can grow into a small ecosystem where:

- creators share games
- players import and explore them
- AI helps design and analyze games
- high-quality community creations can be promoted into the curated experience

Importantly, the project should remain meaningful even if the ecosystem stays small (private side project).

---

## 3. Design Principles

### 3.1 Fixed engine, data-driven games

The app ships a fixed runtime. Games are content/data interpreted by that runtime. No external executable code is downloaded per game.

### 3.2 Mobile-first but web-friendly

The default experience is designed for phones first:

- portrait mode
- thumb-friendly interactions
- high clarity on small screens
- minimal friction to start playing

### 3.3 Constrained expressiveness

The DSL should be expressive enough to support a wide range of puzzle ideas, but constrained enough to keep the system:

- understandable
- analyzable
- robust
- easy to author
- safe to import

### 3.4 Aha-first puzzle design

Games should aim for insight and discovery rather than endless content or brute-force challenge. The best games have this satisfying "aha moment" when a user suddenly understands how to solve it.

### 3.5 Icons over Text

The system should prefer icons, visual rules, and interaction over text-heavy content. Text can still be used, e.g. if games want to build a "story" around the levels (typically text between levels).

### 3.6 Offline-friendly and lightweight

The core system should work without backend infrastructure. Game progress and imported packs should work locally.

### 3.7 Community contribution without heavy ops

The first platform version should allow sharing and importing games without requiring:

- user accounts
- public uploads inside the app
- comments or social feeds
- moderation-heavy infrastructure

---

## 4. Conceptual Model

### 4.1 Platform

The Gridponder app manages multiple **games**.

### 4.2 Game

A **game** is a self-contained package that may include:

- one or more mechanics
- one or more levels
- its own assets, e.g. image tiles and audio, and visual theme
- progression rules
- metadata such as title, description, author, cover image, version

A game is the main unit for:

- distribution
- import/export
- browsing in the platform app
- storage on disk

### 4.3 Runtime model

At runtime, the engine loads:

- the game definition
- the mechanic/rule definitions allowed by the DSL
- the level data
- the assets
- optional hint/replay data

The engine then renders and executes the game deterministically.

---

## 5. Major Components

## 5.1 Gridponder DSL

The DSL defines the content that the engine can interpret.

The DSL v0 covers:

- **entities** — reusable entity kinds with tags and metadata, placed on layered grids
- **layers** — named grid planes (terrain, objects, items, overlays) composing the board
- **actions** — abstract player intents (move, tap, slide, rotate) mapped from gestures
- **systems** — 9 built-in engine modules (navigation, pushing, portals, flood fill, region transforms, etc.) configured by data
- **rules** — declarative event → condition → effect triples for game-specific interactions, with rule recipes for common patterns (inventory, tool use, liquid transitions)
- **goals and lose conditions** — per-level win/loss criteria with partial progress tracking
- **level sequences** — ordered progression with optional branches
- **theme and controls** — visual presentation and input bindings in a separate non-normative file
- **hints / gold paths** — optimal action sequences stored per level
- **variables** — per-level integer counters for tracking state

The DSL should be:

- versioned
- human-readable
- serializable as JSON or a closely related structured format
- strict enough for validation
- extensible over time

The DSL is the most important abstraction boundary in the system.

## 5.2 Game Pack Format

A game pack is the distribution format used to ship a game.

A game pack contains:

- manifest / metadata
- DSL files defining the game and levels
- asset files such as sprites, icons, audio, cover art
- optional hint/replay files
- optional author / license / attribution files

A game pack should be loadable from:

- built-in app assets
- a local file
- a zip archive
- a URL

The pack format should be stable, easy to validate, and easy to unpack.

## 5.3 Gridponder Engine

The engine is the deterministic runtime that interprets game packs.

The engine is responsible for:

- loading and validating game packs
- interpreting DSL definitions
- initializing levels
- running the simulation loop
- applying player actions
- resolving rules and chain reactions
- updating state deterministically
- rendering transitions and animations
- supporting undo/reset
- checking win/loss conditions
- playing hints / gold path previews
- exposing progress and analytics hooks

The engine is the boundary that makes user-contributed content safe and app-store-friendly: external packs can only use what the engine already supports.

## 5.4 Platform App

The platform app is the main product players interact with.

It is responsible for:

- showing available built-in and imported games
- allowing a player to continue where they left off
- opening a game and showing its progression
- launching the engine for gameplay
- storing progress locally
- importing/removing/updating game packs
- optionally syncing or collecting analytics later

This is the “operating system” for Gridponder content.

## 5.5 Creator Tooling

Creator tooling is separate from the player app.

It may include:

- AI-oriented documentation or skills for code agents which allow to create games, levels and assets
- schema validation
- level editor
- solver/analyzer tools

The player app should remain simple even if creator tooling becomes powerful. Three Claude Code skills are already implemented in `.claude/skills/`:

- **revise-level** — analyses, redesigns, or completes a level JSON; evaluates design quality including the "aha moment"
- **test-level** — runs an integration test for a level by executing gold-path moves and taking screenshots after each step
- **tile-gen** — generates game tile or sprite images from a natural language description using local AI (SDXL-Turbo + pixel-art LoRA) running on-device via MPS

These skills document the DSL and tooling in a way that lets a creator focus on expressing intent in natural language. Local image generation is intentional: grid-based tiles are typically 16×96 px, small enough for a lightweight model to run on-device without cloud dependencies.

---

## 6. Proposed High-Level Architecture

### 6.1 Authoring side

A creator works in a repository containing:

- game pack folders
- DSL files
- assets
- validation scripts
- optional creator tooling
- optional AI assistant instructions / skill definitions

Typical flow:

1. create a new game pack folder
2. define metadata and assets
3. define mechanics and levels in the DSL
4. preview locally using the engine or a dev app
5. iterate on gameplay and hints
6. package the result
7. share it as a folder, zip, or hosted artifact

### 6.2 Runtime side

The platform app:

1. loads built-in game packs
2. discovers imported game packs stored locally
3. displays them in the library
4. lets the player open a game
5. uses the engine to interpret and play its content
6. records progress separately from the pack content

### 6.3 Sharing side

A creator shares a game pack by:

- sending a zip file
- sending a URL to a zip file
- sending a URL to a hosted pack folder or manifest
- providing a QR code that resolves to an import URL

The platform app imports the pack, validates it, stores it locally, and makes it playable.

---

## 7. Game Pack Format (Conceptual)

A game pack should be a self-contained folder/archive with a stable structure.

Example conceptual structure:

```text
my-game-pack/
  manifest.json
  game.json
  theme.json
  levels/
    level_001.json
    level_002.json
  assets/
    sprites/
    icons/
    audio/
    cover.png
  metadata/
    author.json
    license.txt
    README.md
```

`game.json` contains the normative game definition (entity kinds, systems, rules, actions, level sequence). `theme.json` contains non-normative visual presentation and input bindings — the same game semantics can have different themes for different platforms.

This exact structure can be refined later, but the important point is:

- the pack is simple
- human-inspectable
- portable
- validatable
- free of executable code

### 7.1 Required pack metadata

Each pack should include metadata such as:

- game id
- title
- version
- DSL version
- author
- description
- entry point
- asset manifest
- minimum supported engine/app version

### 7.2 Optional pack metadata

Optional fields may include:

- language options
- license
- website/source URL
- attribution

---

## 8. Engine Responsibilities in More Detail

The engine must be powerful enough to support varied puzzle mechanics while remaining deterministic and constrained.

## 8.1 Runtime state model

The engine should manage:

- current game
- current level
- current board/grid state
- entity state
- action history
- transient animation state
- hint playback state

## 8.2 Simulation lifecycle

Each player action triggers a deterministic **turn** executed in 7 phases:

1. **Input Validation** — check action legality
2. **Action Resolution** — primary action executes (avatar moves, tiles slide, overlay moves)
3. **Movement Resolution** — secondary movement (objects pushed, portals trigger)
4. **Interaction Resolution** — reserved for future systems (v0 handles interactions via rules)
5. **Cascade Resolution** — rules evaluate against accumulated events; effects may trigger further events up to a bounded cascade depth
6. **NPC Resolution** — follower NPCs move according to their behavior
7. **Goal Evaluation** — win and lose conditions checked

Animation generation and state persistence happen after the turn completes.

## 8.3 Determinism

Given the same pack, level, and action sequence, the engine should always produce the same resulting state. This is important for:

- hints
- replays
- testing
- debugging
- solver tooling
- AI-assisted design

## 8.4 Undo / replay support

The engine should support:

- step-by-step undo
- full level reset
- hint system support via the gold path and specific steps in it
- replay playback from a stored action sequence

## 8.5 Validation and error handling

If a game pack is invalid, the engine/platform should fail gracefully with clear diagnostics for developers and safe error messages for players.
