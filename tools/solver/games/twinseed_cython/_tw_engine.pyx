# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""
Cython hot-path for the Twinseed fast solver.

Provides apply_cy(state, action_idx, neighbors, cells_len) returning
(new_state: bytes, won: bool).  All bookkeeping is done in C-typed local
variables with a stack-allocated output buffer, so no heap allocation
happens during the critical path.

action_idx mapping (same as twinseed_fast.py ACTIONS order):
  0 = move_up, 1 = move_down, 2 = move_left, 3 = move_right, 4 = clone
"""

from libc.string cimport memcpy
from cpython.bytes cimport PyBytes_FromStringAndSize

# ---------------------------------------------------------------------------
# Constants (compile-time defines)
# ---------------------------------------------------------------------------

DEF GROUND_VOID        = 0
DEF GROUND_EMPTY       = 1
DEF GROUND_GARDEN_PLOT = 2
DEF GROUND_PLANTED     = 3
DEF GROUND_WATER       = 4
DEF GROUND_BRIDGE      = 5
DEF GROUND_ICE         = 6
DEF GROUND_WATER_CRATE = 7

DEF OBJ_NONE        = 0
DEF OBJ_SEED_BASKET = 1
DEF OBJ_ROCK        = 2
DEF OBJ_WOOD        = 3
DEF OBJ_METAL_CRATE = 4
DEF OBJ_TORCH       = 5
DEF OBJ_PICKAXE     = 6

DEF INV_NONE    = 0
DEF INV_TORCH   = 1
DEF INV_PICKAXE = 2

DEF CLONE_INACTIVE = 255

DEF MAX_CELLS = 256   # upper bound on W*H (safe for 16×16 board)


# ---------------------------------------------------------------------------
# Inline helpers
# ---------------------------------------------------------------------------

cdef inline int ground_of(unsigned char* cells, int pos) nogil:
    return cells[pos] & 7

cdef inline int obj_of(unsigned char* cells, int pos) nogil:
    return (cells[pos] >> 3) & 7

cdef inline bint is_walkable(int g) nogil:
    return g == GROUND_EMPTY or g == GROUND_GARDEN_PLOT or g == GROUND_PLANTED \
        or g == GROUND_WATER or g == GROUND_BRIDGE or g == GROUND_ICE \
        or g == GROUND_WATER_CRATE

cdef inline bint is_solid(int o) nogil:
    return o == OBJ_SEED_BASKET or o == OBJ_ROCK or o == OBJ_WOOD or o == OBJ_METAL_CRATE

cdef inline bint is_pushable(int o) nogil:
    return o == OBJ_SEED_BASKET or o == OBJ_WOOD or o == OBJ_METAL_CRATE

cdef inline bint is_pickup(int o) nogil:
    return o == OBJ_TORCH or o == OBJ_PICKAXE


# ---------------------------------------------------------------------------
# Win check (no remaining garden_plot)
# ---------------------------------------------------------------------------

cdef inline bint check_win(unsigned char* cells, int cells_len) nogil:
    cdef int i
    for i in range(cells_len):
        if (cells[i] & 7) == GROUND_GARDEN_PLOT:
            return 0
    return 1


# ---------------------------------------------------------------------------
# Object ice slide
# ---------------------------------------------------------------------------

cdef void slide_obj(unsigned char* cells, int pos, int obj, int dir_idx,
                    int* neighbors) noexcept nogil:
    """Slide object from pos in direction dir_idx (neighbors is flattened: neighbors[pos*4 + dir])."""
    cdef int nxt, ng, no, pg
    while 1:
        nxt = neighbors[pos * 4 + dir_idx]
        if nxt < 0:
            break
        ng = cells[nxt] & 7
        if ng == GROUND_VOID or not is_walkable(ng):
            break
        no = (cells[nxt] >> 3) & 7
        if no != OBJ_NONE:
            break
        cells[pos] = cells[pos] & 7        # clear obj at current
        cells[nxt] = (cells[nxt] & 7) | (obj << 3)
        pos = nxt
        pg = cells[pos] & 7
        if obj == OBJ_SEED_BASKET and pg == GROUND_GARDEN_PLOT:
            cells[pos] = (cells[pos] & 0xF8) | GROUND_PLANTED
            cells[pos] = cells[pos] & 7    # clear object
            break
        elif obj == OBJ_SEED_BASKET and pg == GROUND_WATER:
            cells[pos] = cells[pos] & 7    # basket drowns — remove, keep water
            break
        elif obj == OBJ_METAL_CRATE and pg == GROUND_WATER:
            cells[pos] = (cells[pos] & 0xF8) | GROUND_WATER_CRATE
            cells[pos] = cells[pos] & 7    # crate consumed into water_crate ground
            break
        elif pg != GROUND_ICE:
            break


# ---------------------------------------------------------------------------
# Avatar ice slide
# ---------------------------------------------------------------------------

cdef int slide_avatar(unsigned char* cells, int pos, int dir_idx,
                      int* neighbors, int inventory) noexcept nogil:
    """Slide avatar on ice. Returns (new_pos << 8) | new_inventory."""
    cdef int nxt, ng, no, pg, push_dest, pdg, pdo
    while 1:
        nxt = neighbors[pos * 4 + dir_idx]
        if nxt < 0:
            break
        ng = cells[nxt] & 7
        if ng == GROUND_VOID or not is_walkable(ng):
            break
        no = (cells[nxt] >> 3) & 7
        if is_solid(no):
            if is_pushable(no):
                push_dest = neighbors[nxt * 4 + dir_idx]
                if push_dest < 0:
                    break
                pdg = cells[push_dest] & 7
                if pdg == GROUND_VOID or not is_walkable(pdg):
                    break
                pdo = (cells[push_dest] >> 3) & 7
                if pdo != OBJ_NONE:
                    break
                cells[push_dest] = (cells[push_dest] & 7) | (no << 3)
                cells[nxt] = cells[nxt] & 7
                pos = nxt
                pg = cells[push_dest] & 7
                if no == OBJ_SEED_BASKET and pg == GROUND_GARDEN_PLOT:
                    cells[push_dest] = (cells[push_dest] & 0xF8) | GROUND_PLANTED
                    cells[push_dest] = cells[push_dest] & 7
                elif no == OBJ_SEED_BASKET and pg == GROUND_WATER:
                    cells[push_dest] = cells[push_dest] & 7   # basket drowns
                elif no == OBJ_METAL_CRATE and pg == GROUND_WATER:
                    cells[push_dest] = (cells[push_dest] & 0xF8) | GROUND_WATER_CRATE
                    cells[push_dest] = cells[push_dest] & 7
                elif pg == GROUND_ICE:
                    slide_obj(cells, push_dest, no, dir_idx, neighbors)
            break
        # Walk to next cell
        pos = nxt
        pg = cells[pos] & 7
        if pg == GROUND_WATER and inventory != INV_NONE:
            inventory = INV_NONE
        if is_pickup(no):
            inventory = INV_TORCH if no == OBJ_TORCH else INV_PICKAXE
            cells[pos] = cells[pos] & 7
        if pg != GROUND_ICE:
            break
    return (pos << 8) | inventory


# ---------------------------------------------------------------------------
# Public apply function
# ---------------------------------------------------------------------------

def apply_cy(bytes state not None, int action_idx, list neighbors_list,
             int cells_len):
    """
    Apply one action to state.

    Parameters
    ----------
    state        : bytes of length cells_len + 3
    action_idx   : 0=up, 1=down, 2=left, 3=right, 4=clone
    neighbors_list : flat list of ints, length cells_len * 4
                     neighbors_list[pos*4 + dir] = neighbor pos (-1 = OOB)
    cells_len    : W * H

    Returns
    -------
    (new_state: bytes, won: bool)
    If the action is a no-op (blocked), returns (state, False) — same object.
    """
    cdef:
        const unsigned char* src = state
        unsigned char out[MAX_CELLS + 3]
        int avatar_pos, clone_pos, inventory
        int target, tg, to, push_dest, pdg, pdo, pg, nxt
        int new_avatar, new_clone, new_inv
        int tmp, i
        int* neighbors

    # Build a flattened C array of neighbors from the Python list.
    # We use a stack-allocated buffer (up to MAX_CELLS*4 ints).
    cdef int nbuf[MAX_CELLS * 4]
    for i in range(cells_len * 4):
        nbuf[i] = neighbors_list[i]
    neighbors = nbuf

    # Copy state to mutable output buffer
    memcpy(out, src, cells_len + 3)

    avatar_pos = out[cells_len]
    clone_pos  = out[cells_len + 1]
    inventory  = out[cells_len + 2]

    # ------- Clone action -------
    if action_idx == 4:
        if clone_pos == CLONE_INACTIVE:
            out[cells_len + 1] = avatar_pos   # place clone at avatar pos
        else:
            # Teleport: check for solid object at clone cell
            if is_solid((out[clone_pos] >> 3) & 7):
                return state, False            # blocked
            out[cells_len]     = clone_pos
            out[cells_len + 1] = CLONE_INACTIVE
        # Win check (clone action itself can't plant seeds)
        won = check_win(out, cells_len)
        return PyBytes_FromStringAndSize(<char*>out, cells_len + 3), bool(won)

    # ------- Move action -------
    target = neighbors[avatar_pos * 4 + action_idx]
    if target < 0:
        return state, False

    tg = out[target] & 7
    if tg == GROUND_VOID:
        return state, False

    to = (out[target] >> 3) & 7

    if is_solid(to):
        if inventory == INV_TORCH and to == OBJ_WOOD:
            out[target] = out[target] & 7     # burn wood
            avatar_pos = target
        elif inventory == INV_PICKAXE and to == OBJ_ROCK:
            out[target] = out[target] & 7     # break rock
            avatar_pos = target
            inventory = INV_NONE
        elif is_pushable(to):
            push_dest = neighbors[target * 4 + action_idx]
            if push_dest < 0:
                return state, False
            pdg = out[push_dest] & 7
            if pdg == GROUND_VOID or not is_walkable(pdg):
                return state, False
            pdo = (out[push_dest] >> 3) & 7
            if pdo != OBJ_NONE:
                return state, False
            # Push
            out[push_dest] = (out[push_dest] & 7) | (to << 3)
            out[target] = out[target] & 7
            avatar_pos = target
            pg = out[push_dest] & 7
            if to == OBJ_SEED_BASKET and pg == GROUND_GARDEN_PLOT:
                out[push_dest] = (out[push_dest] & 0xF8) | GROUND_PLANTED
                out[push_dest] = out[push_dest] & 7   # remove basket
            elif to == OBJ_SEED_BASKET and pg == GROUND_WATER:
                out[push_dest] = out[push_dest] & 7   # basket drowns
            elif to == OBJ_METAL_CRATE and pg == GROUND_WATER:
                out[push_dest] = (out[push_dest] & 0xF8) | GROUND_WATER_CRATE
                out[push_dest] = out[push_dest] & 7   # crate consumed into water_crate
            elif pg == GROUND_ICE:
                slide_obj(out, push_dest, to, action_idx, neighbors)
        else:
            return state, False

    elif is_pickup(to):
        inventory = INV_TORCH if to == OBJ_TORCH else INV_PICKAXE
        out[target] = out[target] & 7
        avatar_pos = target

    else:
        avatar_pos = target

    # Post-move ground effects
    tg = out[avatar_pos] & 7
    if tg == GROUND_WATER and inventory != INV_NONE:
        inventory = INV_NONE
    if tg == GROUND_ICE:
        tmp = slide_avatar(out, avatar_pos, action_idx, neighbors, inventory)
        avatar_pos = tmp >> 8
        inventory  = tmp & 0xFF

    out[cells_len]     = avatar_pos
    out[cells_len + 2] = inventory

    won = check_win(out, cells_len)
    return PyBytes_FromStringAndSize(<char*>out, cells_len + 3), bool(won)


# ---------------------------------------------------------------------------
# Heuristic and pruning in C
#
# cost_table: array.array('d') of length cells_len*cells_len
#   cost_table[plot_pos * cells_len + basket_pos] = Dijkstra push cost
#   INF (1e300) means no path.
# ---------------------------------------------------------------------------

DEF MAX_BASKETS = 16  # upper bound on baskets/plots per level

cdef double _min_assign(double* ct, int cl,
                        int* baskets, int nb,
                        int* plots, int np_) noexcept nogil:
    """Minimum-cost basket→plot assignment (admissible).

    For nb ≤ 4: exact enumeration of all nb! permutations.
    For nb > 4: sum of each basket's minimum (still admissible).
    """
    cdef double best, c, row_min
    cdef int i, j, k
    cdef int used[MAX_BASKETS]

    if nb == 0:
        return 0.0
    if np_ == 0:
        return 1e300
    if nb < np_:
        return 1e300  # drowned basket(s)

    if nb > 4:
        # Sum-of-minima fallback
        best = 0.0
        for i in range(nb):
            row_min = 1e300
            for j in range(np_):
                c = ct[plots[j] * cl + baskets[i]]
                if c < row_min:
                    row_min = c
            if row_min >= 1e300:
                return 1e300
            best += row_min
        return best

    # Exact enumeration for nb ≤ 4
    # Generate all permutations of np_ items taken nb at a time via backtrack.
    best = 1e300
    for i in range(MAX_BASKETS):
        used[i] = 0

    # For nb ≤ 4, inline recursive permutation via iterative approach with a small stack.
    # We enumerate all choices of nb distinct plots for the nb baskets.
    # Depth-first: perm[i] = plot index for basket i.

    cdef int depth
    cdef int choice_stack[4]
    cdef int idx_stack[4]   # current plot index we're trying at each depth

    for i in range(4):
        choice_stack[i] = -1
        idx_stack[i] = 0

    depth = 0
    idx_stack[0] = 0
    best = 1e300

    while depth >= 0:
        if depth == nb:
            # Evaluate this permutation
            c = 0.0
            for i in range(nb):
                c += ct[plots[choice_stack[i]] * cl + baskets[i]]
                if c >= best:
                    break
            if c < best:
                best = c
            depth -= 1
            if depth >= 0:
                used[choice_stack[depth]] = 0
                idx_stack[depth] += 1
            continue

        # Try next available plot at this depth
        found = 0
        for j in range(idx_stack[depth], np_):
            if not used[j]:
                choice_stack[depth] = j
                used[j] = 1
                idx_stack[depth] = j  # remember where we are
                idx_stack[depth + 1] = 0  # reset next level
                depth += 1
                found = 1
                break

        if not found:
            # Backtrack
            depth -= 1
            if depth >= 0:
                used[choice_stack[depth]] = 0
                idx_stack[depth] += 1

    return best


def heuristic_and_prune_cy(bytes state not None,
                            double[::1] cost_table,
                            int cells_len, int width):
    """
    Compute heuristic and prune flag in one C pass over state.

    Returns (h: float, prune: bool).
      h     = min-cost basket→plot assignment (admissible heuristic).
              float('inf') if any basket has no path to any plot.
      prune = True if any basket has push_dist=inf to every remaining plot.

    Parameters
    ----------
    state      : bytes of length cells_len + 3
    cost_table : array.array('d') of length cells_len * cells_len
    cells_len  : W * H
    width      : board width
    """
    cdef:
        const unsigned char* s = state
        double* ct = &cost_table[0]
        int baskets[MAX_BASKETS]
        int plots[MAX_BASKETS]
        int nb = 0, np_ = 0
        int i, j
        double h, row_min

    # Scan cells for baskets and remaining garden_plot ground
    for i in range(cells_len):
        g = s[i] & 7
        o = (s[i] >> 3) & 7
        if g == GROUND_GARDEN_PLOT:
            if np_ < MAX_BASKETS:
                plots[np_] = i
                np_ += 1
        if o == OBJ_SEED_BASKET:
            if nb < MAX_BASKETS:
                baskets[nb] = i
                nb += 1

    if nb == 0:
        return 0.0, False

    if np_ == 0:
        return float("inf"), True  # baskets remain but no plots — dead state

    if nb < np_:
        return float("inf"), True  # drowned basket(s) — can't fill all remaining plots

    # Prune check: if any basket can't reach any plot, return inf immediately
    for i in range(nb):
        row_min = 1e300
        for j in range(np_):
            if ct[plots[j] * cells_len + baskets[i]] < row_min:
                row_min = ct[plots[j] * cells_len + baskets[i]]
        if row_min >= 1e300:
            return float("inf"), True

    # Min-cost assignment
    h = _min_assign(ct, cells_len, baskets, nb, plots, np_)

    return h, False
