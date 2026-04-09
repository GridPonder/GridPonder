# Gridponder DSL v0.5 — Overview

A high-level map of the DSL: scope, design principles, file structure, and the turn execution pipeline.

## 1. Scope

The Gridponder DSL defines a JSON data format for:

> **Deterministic, discrete, single-player, perfect-information, turn-based, 2D grid puzzle games.**

A game is a sequence of levels, each with goal conditions. The DSL is interpreted by a fixed engine — game packs contain data and assets, never executable code.

---

## 2. Design Principles

### 2.1 Fixed engine, data-driven games
All gameplay is expressed as structured data. The engine ships with the app. Game packs configure what the engine already supports.

### 2.2 Deterministic
Given the same game pack, level, and action sequence, the engine always produces the same result.

### 2.3 Constrained expressiveness
The DSL supports a wide range of 2D grid puzzles but does not try to be a general-purpose game language. Elegance and clarity are preferred over raw power.

### 2.4 JSON-first
The canonical format is JSON, validated by schema. A more concise authoring syntax may be introduced later that compiles to the JSON form.

### 2.5 AI-friendly
The DSL is designed for AI agents to scaffold, inspect, modify, validate, and generate.

### 2.6 Human-readable
Despite being machine-friendly, the format remains understandable by humans.

---

## 3. Architecture — Three Layers

### Layer A: Core Data Model
The board, layers, entities, actor state, variables, goals, and solutions.
This is the **world** — what exists and what the player sees.

### Layer B: Engine Systems
Built-in mechanics configured by data. Each system is an engine module activated and parameterized by the game definition. Systems handle families of related behavior: navigation, pushing, merging, overlays, etc.

### Layer C: Rules
A lightweight **event → condition → effect** model for game-specific interactions that don't warrant their own system. Rules are the declarative glue between systems. **Rule recipes** are documented patterns that express common mechanics (inventory, tool interactions, liquid transitions) purely through rules, avoiding the need for dedicated engine systems.

**Design principle:** If the same rule pattern keeps appearing across many levels or games, it should become a system. Rules handle the long tail of game-specific logic.

---

## 4. Game Pack File Structure

```text
my-game/
  manifest.json          — Pack identity, versioning, compatibility
  game.json              — Shared game definitions
  theme.json             — Visual presentation, input bindings, avatar sprites (non-normative)
  levels/
    level_001.json       — Individual puzzle levels
    level_002.json
    ...
  assets/
    sprites/             — Entity and UI sprites (PNG)
    story/               — Story screen images
    audio/               — Sound effects, music
    cover.png            — Game cover art
  metadata/              — Optional
    author.json
    license.txt
```

---

## 5. Core Concepts

| Concept | Description |
|---------|-------------|
| **Game** | Top-level playable unit. Defines entity kinds, systems, actions, controls, and the level sequence. |
| **Level** | One puzzle instance. Defines board layout, initial state, goals, and solution. |
| **Board** | A bounded 2D grid organized into named layers. Each layer holds entity instances. |
| **Entity Kind** | A reusable definition (e.g., rock, torch, portal) with metadata, tags, animations, and rendering hints. Declared in `game.json`, referenced in levels. |
| **System** | A built-in engine module handling one mechanic family. Configured by data, optionally overridden per level. |
| **Rule** | A declarative event-condition-effect triple for game-specific interactions. Evaluated after system phases, with bounded cascade depth. |
| **Action** | An abstract player intent (e.g., move up, tap cell, rotate). UI gestures map to actions; systems consume actions. |
| **Tag** | A semantic label on an entity kind (e.g., `solid`, `pushable`, `liquid`). Systems use tags to select eligible entities. Tags are necessary but not sufficient — all behavior is explicit in system config. |

---

## 6. Execution Model

When the player performs one action, the engine executes a **turn**:

```
1. Input Validation
   └─ Check action legality

2. Action Resolution
   └─ Primary action executes (avatar moves, tiles slide, overlay moves, etc.)

3. Movement Resolution
   └─ Secondary movement (objects pushed, portals trigger)

4. Interaction Resolution
   └─ Reserved for future systems (v0.5 handles interactions via rules in phase 5)

5. Cascade Resolution (repeats up to max_cascade_depth)
   ├─ Rules evaluate against accumulated events
   ├─ Rule effects execute (may trigger emitters, gravity, spawns)
   ├─ Emitters and gravity resolve
   └─ New events feed back into next cascade pass

6. NPC Resolution
   └─ Follower NPCs move according to their behavior

7. Goal Evaluation
   └─ Win and lose conditions checked
```

Each phase is deterministic. Systems declare which phase(s) they participate in.

---

## 7. System Interaction Protocol

Systems interact through three mechanisms:

1. **Shared state** — All systems read and write the same board, avatar, and variable state. Phase ordering determines who sees what.
2. **Events** — Systems emit typed events during their phase. Rules consume events during cascade resolution.
3. **Phase ordering** — A system in phase 3 always sees the state changes from phase 2. This removes ambiguity about execution order.

Systems never call each other directly. Coordination happens through state and events.

---

## 8. Versioning

- `manifest.json` and `game.json` declare `dslVersion` (v0.5 uses `"0.1.0"`)
- The engine supports specific DSL versions explicitly — no implicit guessing
- If a pack uses an unsupported version, import fails with a clear error
- New mechanics are introduced by adding new system types or new fields to existing structures
- Backward compatibility is maintained where possible

---

## 9. Document Index

| Document | Contents |
|----------|----------|
| [01_manifest.md](01_manifest.md) | Pack manifest schema |
| [02_game.md](02_game.md) | Game definition: entity kinds, animations, actions, systems, level sequence |
| [03_levels.md](03_levels.md) | Level definition: board model, state, goals, lose conditions, solution |
| [04_systems.md](04_systems.md) | System architecture and complete v0.5 system catalog (10 systems) |
| [05_rules.md](05_rules.md) | Rules model: events, conditions, effects, cascade semantics, rule recipes |
| [06_theme.md](06_theme.md) | Theme & controls: visual presentation, input bindings, avatar sprite map |
