"""QueuedEmittersSystem — see docs/dsl/04_systems.md."""
from __future__ import annotations
from collections import deque
from typing import Any, Optional

from .._models import (
    Pos, Entity, GameState, PendingMove, OverlayCursor,
    dir_delta, dir_opposite, is_cardinal, CARDINALS,
)
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem


class QueuedEmittersSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "queued_emitters")

    def execute_npc_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        emitter_kind = config.get("emitterKind", "pipe")
        board = state.board
        events: list[dict] = []

        for mco in board.multi_cell_objects:
            if mco.kind != emitter_kind:
                continue
            exit_raw = mco.params.get("exitPosition")
            if exit_raw is None:
                continue
            exit_pos = Pos.from_json(exit_raw) if not isinstance(exit_raw, Pos) else exit_raw
            exit_dir = mco.params.get("exitDirection")
            spawn_pos = Pos(exit_pos.x + dir_delta(exit_dir)[0], exit_pos.y + dir_delta(exit_dir)[1]) if exit_dir else exit_pos

            queue = mco.params.get("queue", [])

            exit2_raw = mco.params.get("exit2Position")
            if exit2_raw is not None:
                exit2_pos = Pos.from_json(exit2_raw) if not isinstance(exit2_raw, Pos) else exit2_raw
                exit2_dir = mco.params.get("exit2Direction")
                spawn2_pos = Pos(exit2_pos.x + dir_delta(exit2_dir)[0], exit2_pos.y + dir_delta(exit2_dir)[1]) if exit2_dir else exit2_pos
                self._emit_bidirectional(board, mco, events, queue, exit_pos, spawn_pos, exit2_pos, spawn2_pos)
            else:
                idx = mco.params.get("currentIndex", 0)
                if idx >= len(queue):
                    continue
                if board.get_entity("objects", exit_pos) is not None:
                    continue
                if spawn_pos != exit_pos and board.get_entity("objects", spawn_pos) is not None:
                    continue
                val = queue[idx]
                p = {"value": val}
                board.set_entity("objects", spawn_pos, Entity("number", p))
                mco.params["currentIndex"] = idx + 1
                events.append(ev.item_released(mco.id, "number", spawn_pos, p))

        return events

    def _emit_bidirectional(self, board, mco, events, queue, exit1, spawn1, exit2, spawn2):
        pipe_len = len(mco.cells)
        if mco.params.get("pipeSlots") is None:
            slots = [None] * pipe_len
            for i, v in enumerate(queue[:pipe_len]):
                slots[i] = v
            mco.params["pipeSlots"] = slots

        slots = list(mco.params["pipeSlots"])
        last = pipe_len - 1
        if all(v is None for v in slots):
            return

        def clear(exit_p, spawn_p):
            return (board.get_entity("objects", exit_p) is None and
                    (spawn_p == exit_p or board.get_entity("objects", spawn_p) is None))

        can1 = clear(exit1, spawn1)
        can2 = clear(exit2, spawn2)

        if slots[0] is not None and can1:
            val = slots[0]
            p = {"value": val}
            board.set_entity("objects", spawn1, Entity("number", p))
            events.append(ev.item_released(mco.id, "number", spawn1, p))
            slots[0] = None
        if slots[last] is not None and can2:
            val = slots[last]
            p = {"value": val}
            board.set_entity("objects", spawn2, Entity("number", p))
            events.append(ev.item_released(mco.id, "number", spawn2, p))
            slots[last] = None

        new_slots = [None] * pipe_len
        for i, v in enumerate(slots):
            if v is None:
                continue
            d1 = i
            d2 = last - i
            if d1 < d2:
                target = i - 1
            elif d2 < d1:
                target = i + 1
            else:
                if can1 and not can2:
                    target = i - 1
                elif can2 and not can1:
                    target = i + 1
                else:
                    target = i
            target = max(0, min(last, target))
            if new_slots[target] is not None:
                target = i
            new_slots[target] = v

        mco.params["pipeSlots"] = new_slots

