## Plain-English mechanic spec

This is a Sokoban-like grid puzzle game where **boxes are built out of sides**.

Each grid cell may contain:

* floor or wall
* optionally a target
* the player
* zero or more **box side fragments**

Each box fragment is basically a 4-bit wall segment:

* `U` = top side present
* `R` = right side present
* `D` = bottom side present
* `L` = left side present

Examples:

* single side: `U`, `R`, `D`, or `L`
* corner: `U+R`, `R+D`, `D+L`, `L+U`
* opposite pair: `U+D` or `L+R`
* three sides: any mask with 3 bits set
* full box: `U+R+D+L`

A “box” is still only **one grid cell large**. The state of that cell says which sides exist.

Background: we can use grass tiles for normal cells and a special tile for the target cells (where we need to move boxes).

---

## Movement rules

On each player input, do this:

1. The player chooses a direction.

2. The player may move into an adjacent non-wall cell if not blocked by a **closed side** of a box on that boundary.

3. If the player pushes against a box from outside, the box can be pushed **only if that side exists on the box** and the destination is legal.

4. If the player is **inside** a partial or full box, and tries to move through one of the box’s existing sides, the box moves with the player by one cell in that direction.

5. Connected box matter should behave rigidly for that move:

   * if moving one box part implies another touching part must also move, they all move together
   * if any required part cannot move, the whole move is cancelled

---

## Assembly rules

When multiple fragments end up on the same cell:

* if they occupy **different sides**, merge them into one box state whose mask is the bitwise OR of those sides
* if they overlap on the same side, treat that as invalid or just keep one copy
* merging happens **after movement resolution**

Examples:

* `U` + `R` => `U+R`
* `U+R` + `D` => `U+R+D`
* `L+R` + `U+D` => full box
* `U` + `D` => vertical opposite pair
* `L` + `R` => horizontal opposite pair

A fully assembled box is simply the mask `U+R+D+L`.

---

## Collision / blocking rules

A box blocks movement only on sides that exist.

That means:

* entering a cell from the left is blocked if the cell contains a box with `L`
* entering from the right is blocked if the cell contains `R`
* entering from above is blocked if the cell contains `U`
* entering from below is blocked if the cell contains `D`

This is the key idea: **a partial box is only solid where it has a side**.

So if a box has opposite sides only, the player may still stand “inside” it by entering through an open boundary.

---

## Win condition

Win when every target cell is occupied by a box state. Only a **full box** counts.

---

## Design note for “inside the box”

You do **not** need a special “inside” state.

The player is “inside a box” if:

* player and box occupy the same cell
* the box mask does **not** fully block all access in the relevant way

In practice, just allow player + box to share a tile, and use side-based collision when entering/leaving.

---

## Simple rules to implement

### Entering a cell

A move into a cell is blocked if the destination cell has a side on the incoming boundary.

### Pushing from outside

If the destination cell contains a box side on the incoming boundary, the box is pushed.

### Carrying from inside

If the current cell contains player + box, and the player moves through a side that exists, the box moves with the player.

### Merging

After all moves, OR together all box side masks on the same tile.

---

## Level design wists that keep the core intact

Certain floor tiles teleport **only the player**, not boxes.
We can re-use the tile/behaviour from the carrot quest game.

Similarly, we can also use rock and pickaxe from the carrot quest game to make levels more interesting.

