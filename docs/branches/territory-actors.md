# Branch guide: `feature/territory-actors`

**Status:** unpushed, 21 commits on top of `main` (`7231789`). Formerly named
`feature/coupled-actors`.

This branch is a working artifact, not a permanent part of the docs. **Delete this
file as part of the merge** once the questions in [Open decisions](#open-decisions)
are settled.

---

## 1. What this branch adds

Support for **multiple actor entities that claim territory as they move**, and a
goal that asks for that territory to be divided completely and equally between
them. Everything is data-driven: two new engine systems, one goal type, two lose
conditions, plus the app and solver support to play and search them. No rules
engine changes, no game-specific engine branches.

It takes the DSL from **0.7 to 0.10** in three increments, and both engines to
`0.10.0`:

| Version | Adds |
|---------|------|
| 0.8 | `coupled_actors` system, `balance` goal |
| 0.9 | `individual_actors` system, per-level `systemOverrides` |
| 0.10 | `balance_unreachable` lose condition |

---

## 2. Mechanics inventory

Everything this branch claims in the shared DSL namespace. **If your branch adds
any of these under a different name, we have a duplicate to resolve.**

| Mechanic | Kind | Spec |
|---|---|---|
| `coupled_actors` | system | [04_systems.md §2.11](../dsl/04_systems.md) |
| `individual_actors` | system | [04_systems.md §2.12](../dsl/04_systems.md) |
| `balance` | goal type | [03_levels.md](../dsl/03_levels.md) |
| `balance_budget_exhausted` | lose condition | [03_levels.md](../dsl/03_levels.md) |
| `balance_unreachable` | lose condition | [03_levels.md](../dsl/03_levels.md) |
| `systemOverrides` | level field | [03_levels.md](../dsl/03_levels.md) |
| `position` action param type | action enumeration | `engines/python/action_enum.py` |
| `territory` layer name | layer convention | [02_game.md](../dsl/02_game.md) |
| directional sprites | theme | `sprites.idle.<dir>`, `sprites.walk.<dir>` |

### The two actor systems

Both keep actors as ordinary layer entities and share the same optional `claim`
config (mover kind → claim-mark kind written into a territory layer).

- **`coupled_actors`** — one `move` action moves *every* actor one cell in that
  direction. Actors resolve front-first, so a trailing actor can legally follow
  into a cell the one ahead just vacated. Actors blocked by walls or edges stay
  put while the rest continue.
- **`individual_actors`** — `selectAction` (default `tap_cell`, needs a `position`
  param) selects one actor; `move` then moves only it. Optional `budgets` caps each
  actor's successful moves.

### The balance goal and its two lose conditions

`balance` tallies owner kinds on a territory layer against the claimable cells on
a ground layer. `requireComplete` demands every claimable cell be owned;
`requireEqual` demands all owners hold identical counts.

The two lose conditions both exist because claims are **irreversible** — an owner
that overshoots its equal share can never come back down, so the level is dead the
moment it overshoots:

- **`balance_unreachable`** — the general form. Fires when any owner exceeds its
  equal share, or when `claimable` isn't divisible by the owner count. Needs no
  actor or budget wiring, and works in both control modes.
- **`balance_budget_exhausted`** — the `individual_actors` form. Same over-claim
  check, plus: fails when an owner's remaining move budget is smaller than the
  number of cells it still needs.

They overlap deliberately. `balance_unreachable` was extracted as the standalone,
mode-agnostic half.

---

## 3. Merge collision map

Shared dispatch points any second branch adding a system, goal, or lose condition
will also edit. Ordered by how likely a conflict is.

| File | What we changed | Risk |
|---|---|---|
| `docs/dsl/VERSION` | `0.7` → `0.10` | **Certain** if you also bumped |
| `engines/dart/pubspec.yaml`, `engines/python/__init__.py` | → `0.10.0` | **Certain** if you also bumped |
| `engines/dart/.../systems/system_registry.dart` | +2 entries in `_factories` | High |
| `engines/python/_systems/__init__.py` | +2 entries in `_REGISTRY` | High |
| `engines/dart/.../engine/goal_evaluator.dart` | +`case 'balance'` | High |
| `engines/dart/.../engine/lose_evaluator.dart` | +2 `case`s | High |
| `engines/python/_goal.py` | +goal and +2 lose branches | High |
| `docs/dsl/02_game.md`, `03_levels.md`, `04_systems.md` | new sections | High |
| `app/lib/src/screens/play_screen.dart` | **heavily rewritten** (~700 lines) | **Highest** |
| `app/lib/src/widgets/board_renderer.dart` | territory layer, sprites | Medium |
| `engines/python/action_enum.py` | `position` param enumeration | Medium |
| `engines/dart/.../engine/phase_runner.dart`, `turn_engine.dart` | override plumbing | Medium |
| `engines/dart/.../models/` (`event`, `game_definition`, `game_state`) | new events, overrides | Medium |
| `engines/python/` (`_events`, `_models`, `_game_def`, `_turn_engine`) | same, python side | Medium |
| `tools/solver/solve.py` | +1 game dispatch case | Low |
| `tools/solver/engine_adapter.py` | balance heuristic + pruning | Low |
| `.gitignore` | dev pack wiring | Low |

The registry and dispatch files are additive — conflicts there should resolve by
**keeping both entries**. `play_screen.dart` is the one to be careful with: it was
restructured, not just appended to, so a textual merge will likely mislead. If your
branch touches it, we should merge that file by hand.

---

## 4. Overlap checklist

Run these against your branch. The obvious mechanics aren't the real risk — nobody
reinvents `coupled_actors` by accident. **The risk is the incidental generic
extensions**, which a second game plausibly needed and solved under a different
name.

Check these first:

- [ ] **Per-level system toggles.** We added `systemOverrides` (enable/disable and
      re-config any system per level). Did you add your own per-level system
      switching? *Most likely duplicate.*
- [ ] **Cell-targeting actions.** We added a `position` action param type that
      enumerates every board cell, plus the `tap_cell` convention. Did you add a
      tap/click/select action?
- [ ] **Per-entity resource budgets.** Ours is `individual_actors.budgets` (counted
      successful moves). If you added a general resource or move-limit mechanic,
      one of these should probably become the generic one.
- [ ] **Selection state.** We store the selected actor in a runtime variable
      (`selectedActorKind`). Did you add a selection concept?

Then the rest:

- [ ] **Multi-entity movement.** Any system moving several entities from one action?
      Compare against `coupled_actors` front-first resolution.
- [ ] **Ownership / claiming.** Any per-cell ownership marking? Compare to the
      `claim` config and the `territory` layer convention.
- [ ] **Coverage or partition goals.** Any goal about filling or dividing the board?
      Compare to `balance` (`requireComplete` / `requireEqual` may already cover it).
- [ ] **Dead-end lose conditions.** Any "this is now unwinnable" condition? Ours are
      the two balance ones; a shared abstraction may be worth extracting.
- [ ] **Directional sprites.** We added `sprites.idle.<dir>` / `sprites.walk.<dir>`
      driven by a theme `paramMapping`. Did you add facing or animation?
- [ ] **Test/dev tooling.** We added `--extra-packs-dir` to the gold-path suite and
      bundled-pack discovery from an `assets/packs-private` dev root.

---

## 5. Open decisions

1. **DSL version renumbering.** `main` is at 0.7; we consumed 0.8, 0.9, and 0.10.
   If your branch also bumped from 0.7, our numbers collide and whichever branch
   merges second has to renumber — its `VERSION`, both engine versions, and the
   `dslVersion` / `minEngineVersion` in every pack that uses the new features.
   Worth agreeing on the order *before* either of us pushes.

   Note that `minEngineVersion` is parsed but never actually compared in either
   loader, so it's documentary only — renumbering it is cheap.

2. **Pack identity in the public repo.** This branch carries private-pack
   references into a public repo: a `tk_smoke` fixture in
   `engines/python/_fixtures/`, `tools/solver/test_three_kingdoms_solver.py`, a
   `three_kingdoms` case in `solve.py`, `wei`/`shu`/`wu` entity kinds across the
   engine and app tests, and the config examples in `docs/dsl/04_systems.md`.

   No levels, gold paths, or solutions are exposed, and the systems themselves are
   public by design — the tenets require engine support to land as generic,
   reusable DSL features. But the tenets *also* say to keep distinctive private
   mechanics out of public docs, and the pack's name and faction kinds are visible.
   **This needs a supervisor call before the push**, not a merge-time one. The
   cheap fix, if wanted, is renaming the fixture and genericizing the doc examples;
   the expensive one is scrubbing entity kinds across ~1,500 lines of tests.

3. **Solver dispatch.** `solve.py` still keys on game id, so each pack needs a case
   even when it solves through the fully generic path. The `balance` heuristic in
   `engine_adapter.py` is keyed on `goal.type`, not the pack, so it needs no such
   entry. If your branch also touched that dispatch, it may be worth replacing the
   whole `if game == ...` chain with goal-driven selection.

4. **This file.** Delete it when we merge.
