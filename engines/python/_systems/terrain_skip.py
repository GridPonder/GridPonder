"""TerrainSkipSystem — see docs/dsl/04_systems.md."""
from __future__ import annotations

from .._models import Pos, Entity, dir_delta, GameState
from .._game_def import GameDef
from ._base import GameSystem


class TerrainSkipSystem(GameSystem):
    """Transport an actor across a contiguous terrain region in one step.

    When an actor steps onto a cell tagged ``terrainTag``, it is immediately
    moved to the first non-terrain cell beyond the far edge of that contiguous
    terrain region in the direction of travel.  No extra events are emitted, so
    trail/budget rules do not fire a second time for the transit.

    If the exit cell is blocked (rock, OOB, occupied), the actor is bounced
    back to fromPosition from the event — no trail or budget changes apply.
    """

    def __init__(self, sys_id: str):
        super().__init__(sys_id, "terrain_skip")

    def _config(self, game: GameDef) -> dict:
        cfg = game.system_config(self.id)
        return {
            "terrainTag": cfg.get("terrainTag", "water"),
            "groundLayer": cfg.get("groundLayer", "ground"),
            "actorLayer": cfg.get("actorLayer"),
            "actorPositionVariable": cfg.get("actorPositionVariable"),
            "trailClearing": cfg.get("trailClearing", []),
            "excludeActorKinds": cfg.get("excludeActorKinds", []),
            "exitBlockLayers": cfg.get("exitBlockLayers", []),
            "exitHazardLayers": cfg.get("exitHazardLayers", []),
            "exitFoodLayers": cfg.get("exitFoodLayers", []),
            "exitPortal": cfg.get("exitPortal"),
        }

    def _chained_portal_exit(self, board, pos: Pos, exit_portal_cfg: dict | None, game: GameDef) -> Pos | None:
        """If ``pos`` carries a portal-tagged entity (per ``exit_portal_cfg``),
        return the paired portal's position — or None if unset, ``pos`` isn't
        a portal, or no pair exists.

        Mirrors ``PortalsSystem._portal_at``/``_find_exit_portal``; duplicated
        rather than shared because a silent terrain_skip relocation never
        emits the actor_entered event the portals system reacts to, so it
        cannot see this landing on its own.
        """
        if not exit_portal_cfg:
            return None
        tags = exit_portal_cfg.get("tags") or ["teleport"]
        match_key = exit_portal_cfg.get("matchKey", "channel")
        for layer in board.layers.values():
            entity = layer.get(pos)
            if entity is None:
                continue
            if not any(game.has_tag(entity.kind, t) for t in tags):
                continue
            channel_value = entity.param(match_key)
            if channel_value is None:
                return None
            for other_layer in board.layers.values():
                for candidate_pos, candidate in other_layer.entries():
                    if candidate_pos == pos:
                        continue
                    if candidate.kind != entity.kind:
                        continue
                    ch = candidate.param(match_key)
                    if ch is not None and str(ch) == str(channel_value):
                        return candidate_pos
            return None
        return None

    def _clear_actor_trail(self, state: GameState, cfg: dict, actor_kind: str) -> None:
        for tc in cfg.get("trailClearing", []):
            if tc.get("actorKind") != actor_kind:
                continue
            trail_layer_id = tc.get("trailLayer")
            trail_kind = tc.get("trailKind")
            restore_kind = tc.get("restoreKind")
            budget_var = tc.get("budgetVariable")
            layer = state.board.layers.get(trail_layer_id)
            if layer is None:
                break
            to_restore = [pos for pos, ent in layer.entries() if ent.kind == trail_kind]
            for pos in to_restore:
                new_ent = Entity(restore_kind) if restore_kind else None
                state.board.set_entity(trail_layer_id, pos, new_ent)
            if to_restore and budget_var is not None:
                current = state.variables.get(budget_var, 0)
                state.variables[budget_var] = (current if isinstance(current, int) else 0) + len(to_restore)
            break

    def execute_cascade_resolution(
        self, trigger_events: list[dict], state: GameState, game: GameDef
    ) -> list[dict]:
        cfg = self._config(game)
        actor_layer_id = cfg["actorLayer"]
        if not actor_layer_id:
            return []

        actor_layer = state.board.layers.get(actor_layer_id)
        if actor_layer is None:
            return []

        terrain_tag = cfg["terrainTag"]
        ground_layer_id = cfg["groundLayer"]

        for e in trigger_events:
            if e["type"] != "actor_entered":
                continue

            entered_raw = e.get("position")
            if entered_raw is None:
                continue
            entered_pos = (
                entered_raw if isinstance(entered_raw, Pos)
                else Pos.from_json(entered_raw)
            )

            # Actor must still be at the entered position.
            actor = actor_layer.get(entered_pos)
            if actor is None:
                continue

            # Skip terrain transport for excluded actor kinds.
            actor_kind_early = e.get("kind") or actor.kind
            if actor_kind_early in cfg["excludeActorKinds"]:
                continue

            # Entry cell must carry the terrain tag.
            ground_ent = state.board.get_entity(ground_layer_id, entered_pos)
            if ground_ent is None or not game.has_tag(ground_ent.kind, terrain_tag):
                continue

            # Direction of travel from the event.
            dir_str = e.get("direction")
            if not dir_str:
                continue
            dx, dy = dir_delta(dir_str)

            # Walk forward through contiguous terrain to find the far edge.
            scan = entered_pos
            while True:
                nxt = Pos(scan.x + dx, scan.y + dy)
                if not state.board.is_in_bounds(nxt):
                    break
                nxt_ground = state.board.get_entity(ground_layer_id, nxt)
                if nxt_ground is None or not game.has_tag(nxt_ground.kind, terrain_tag):
                    break
                scan = nxt

            # Exit = one step beyond the last terrain cell.
            exit_pos = Pos(scan.x + dx, scan.y + dy)

            # Validate exit.
            exit_valid = state.board.is_in_bounds(exit_pos) and not state.board.is_void(exit_pos)
            if exit_valid:
                exit_ground = state.board.get_entity(ground_layer_id, exit_pos)
                if exit_ground is not None and not game.has_tag(exit_ground.kind, "walkable"):
                    exit_valid = False
            if exit_valid and actor_layer.get(exit_pos) is not None:
                exit_valid = False
            if exit_valid:
                for layer_check in cfg["exitBlockLayers"]:
                    layer_id = layer_check.get("layer")
                    block_tags = layer_check.get("blockTags", [])
                    if layer_id and block_tags:
                        exit_entity = state.board.get_entity(layer_id, exit_pos)
                        if exit_entity is not None:
                            kind_def = game.entity_kinds.get(exit_entity.kind, {})
                            entity_tags = kind_def.get("tags", []) if isinstance(kind_def, dict) else getattr(kind_def, "tags", [])
                            if any(t in entity_tags for t in block_tags):
                                exit_valid = False
                                break

            if not exit_valid:
                # Bounce back: return actor to the cell it came from.
                from_raw = e.get("fromPosition")
                if from_raw is not None:
                    from_pos = (
                        from_raw if isinstance(from_raw, Pos)
                        else Pos.from_json(from_raw)
                    )
                    state.board.set_entity(actor_layer_id, entered_pos, None)
                    state.board.set_entity(actor_layer_id, from_pos, actor)
                    pos_var = cfg["actorPositionVariable"]
                    if pos_var is not None:
                        state.variables[pos_var] = [from_pos.x, from_pos.y]
                break

            # Clear actor trail and accumulate freed cells into budget.
            actor_kind = e.get("kind") or actor.kind
            self._clear_actor_trail(state, cfg, actor_kind)

            # If the water-crossing exit lands directly on a portal, chain
            # through to its paired exit — see _chained_portal_exit.
            final_pos = self._chained_portal_exit(
                state.board, exit_pos, cfg.get("exitPortal"), game
            ) or exit_pos

            # Relocate actor silently.
            state.board.set_entity(actor_layer_id, entered_pos, None)
            state.board.set_entity(actor_layer_id, final_pos, actor)
            pos_var = cfg["actorPositionVariable"]
            if pos_var is not None:
                state.variables[pos_var] = [final_pos.x, final_pos.y]

            # Check exit cell for hazards and set kill variables directly.
            # No actor_entered event is emitted for the transit, so rules
            # cannot detect landing on a hazard — handle it inline here.
            for hazard_check in cfg.get("exitHazardLayers", []):
                layer_id = hazard_check.get("layer")
                hazard_tags = hazard_check.get("hazardTags", [])
                var_name = hazard_check.get("variable")
                var_value = hazard_check.get("value")
                if layer_id and var_name and hazard_tags:
                    exit_entity = state.board.get_entity(layer_id, final_pos)
                    if exit_entity is not None:
                        kind_def = game.entity_kinds.get(exit_entity.kind, {})
                        entity_tags = kind_def.get("tags", []) if isinstance(kind_def, dict) else getattr(kind_def, "tags", [])
                        if any(t in entity_tags for t in hazard_tags):
                            state.variables[var_name] = var_value
                            break

            # Check exit cell for food and award it directly, same reasoning
            # as the hazard check above: no actor_entered event fires for the
            # transit, so eat_food_* rules never see the landing cell and the
            # actor silently overlaps food without collecting it. A food kind
            # is identified by a tag "<amountTagPrefix><N>" (e.g. "food_v7"),
            # awarded to "<budgetVariablePrefix><color>" where color is the
            # last "_"-separated segment of the actor's kind (snake_red ->
            # red), matching the eat_food_N_<color> rule naming convention.
            for food_check in cfg.get("exitFoodLayers", []):
                layer_id = food_check.get("layer")
                food_tag = food_check.get("foodTag", "food")
                amount_prefix = food_check.get("amountTagPrefix", "food_v")
                budget_prefix = food_check.get("budgetVariablePrefix", "moveBudget_")
                if not layer_id:
                    continue
                exit_entity = state.board.get_entity(layer_id, final_pos)
                if exit_entity is None:
                    continue
                kind_def = game.entity_kinds.get(exit_entity.kind, {})
                entity_tags = kind_def.get("tags", []) if isinstance(kind_def, dict) else getattr(kind_def, "tags", [])
                if food_tag not in entity_tags:
                    continue
                amount = None
                for t in entity_tags:
                    if t.startswith(amount_prefix) and t[len(amount_prefix):].isdigit():
                        amount = int(t[len(amount_prefix):])
                        break
                if amount is None:
                    continue
                color = actor_kind.rsplit("_", 1)[-1]
                budget_var = f"{budget_prefix}{color}"
                current = state.variables.get(budget_var, 0)
                state.variables[budget_var] = (current if isinstance(current, int) else 0) + amount
                state.board.set_entity(layer_id, final_pos, None)
                break

            break  # one transport per cascade pass

        return []