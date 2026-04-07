# GridPonder Level Design Principles

## The Aha Moment

Every level except pure mechanic-introduction levels must have one.
An aha moment is a sudden realisation that changes how the player sees the
puzzle — the "oh, THAT'S what I'm supposed to do" feeling.

Good aha moments in puzzle games come from:
- **Subverted assumptions**: the obvious first move turns out to be wrong in
  an instructive way (not a frustrating dead end)
- **Hidden constraint**: the player realises there's an ordering or
  sequencing requirement they hadn't noticed
- **Dual purpose**: an element does two things; the player realises they need
  to use it for the second purpose, not the obvious first
- **Reversal**: the solution involves moving in the unexpected direction
- **Cascade**: one action triggers a chain that the player didn't anticipate

The aha moment should be **earned** (the player could reason their way to it)
and **memorable** (not a lucky guess).

## Difficulty Curve Within a World

- Level 1: Introduce the primary mechanic with almost no ambiguity.
- Level 2: Add one complication (obstacle, constraint, or second element).
- Level 3: Combine the mechanics in a way that produces a genuine insight.
- Level 4+: Deepen complexity; may introduce secondary mechanics.

A world should feel like a mini-arc: each level builds on the previous one.

## Tightness and Elegance

A tight level has:
- **Exactly one intended path** (or a very small equivalence class)
- **No wasted elements**: every tile on the board serves a purpose
- **No cheap escapes**: brute force and random moves should fail instructively

A loose level has many paths to the goal, which dilutes the aha moment.
If a level can be solved in multiple ways, it probably doesn't have a strong
aha moment — redesign to eliminate the alternatives.

## Validating a Level

Before committing a design:
1. Simulate the intended solution step by step (track every tile).
2. Try the most obvious wrong approach and confirm it fails.
3. Try one or two random sequences and confirm they don't accidentally win.
4. Count the moves — is the level too long (boring) or too short (trivial)?

For number universe levels, useful design heuristics:
- 2-move levels: appropriate for mechanic introductions only.
- 3-5 moves: sweet spot for world levels 2-4.
- 6-8 moves: appropriate for later, more complex levels.

## Number Universe Specific

### The Merge Cascade Pattern
Numbers merge on contact (sum). This enables chains: A + B = C, then C + D.
The aha moment in cascade levels is often that the player must *not* make the
obvious merge first, because it creates the wrong number for the next step.

### Positioning Matters
The goal grid or sequence forces the player to think about WHERE a number
will land, not just WHAT value to create. Combine positional and value
constraints for richer puzzles.

### Rocks as Shapers
Rocks don't just block — they shape the SPACE in which tiles move.
Placing a rock changes the merge order and landing positions. A well-placed
rock can make a seemingly open board have only one correct sequence.

### maxMoves as a Teaching Tool
A tight move limit (e.g., 3 moves for something that looks like it needs 4)
forces the player to find the efficient path. It signals "there is a trick
here — find it." Use sparingly; don't punish exploration unnecessarily.

## Anti-Patterns to Avoid

- **Guess-and-check**: the player has no way to reason toward the solution
- **Trial-and-error sequences**: the solution is just "try all permutations"
- **Arbitrary complexity**: adding more tiles/cells without adding insight
- **Misleading rules text**: the rules panel must accurately describe what
  the mechanics actually do (bugs in rule text destroy trust)
