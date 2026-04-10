"""
Per-game mutation configuration for mutate_and_test.py.

Each game entry declares which layers can be mutated and how:

  mutable_layers : dict of layer_name → layer config
    format         : "sparse" or "dense"
    mutable_kinds  : list of kind strings eligible for repositioning;
                     None means all kinds are mutable
  mutable_avatar : whether the avatar start position can be moved
  has_heuristic  : whether the game solver supports A* (implements heuristic())

The mutation engine uses only generic DSL operations:

  Sparse layer → move an entry to a different empty walkable cell
  Dense layer  → swap two cells whose kinds are both in mutable_kinds

No game-specific mutation logic is needed here.  Game-specific structural
validity (e.g. box fragment pairing) is checked in mutate_and_test.py.
"""

GAME_CONFIGS: dict = {
    "box_builder": {
        "game_module": "box_builder",
        "mutable_layers": {
            # Fragments, rocks, and pickaxes can be repositioned
            "objects": {
                "format": "sparse",
                "mutable_kinds": ["box_fragment", "rock", "pickaxe"],
            },
            # Box targets can be repositioned
            "markers": {
                "format": "sparse",
                "mutable_kinds": ["box_target"],
            },
            # Swapping empty↔void changes the board shape
            "ground": {
                "format": "dense",
                "mutable_kinds": ["empty", "void"],
            },
        },
        "mutable_avatar": True,
        "has_heuristic": True,
    },

    "rotate_flip": {
        "game_module": "rotate_flip",
        "mutable_layers": {
            # Coloured tiles in the initial arrangement can be repositioned
            "objects": {
                "format": "sparse",
                "mutable_kinds": None,  # all tile kinds
            },
        },
        "mutable_avatar": False,
        "has_heuristic": False,
    },

    "number_crunch": {
        "game_module": "number_crunch",
        "mutable_layers": {
            # Number tiles can be repositioned
            "objects": {
                "format": "sparse",
                "mutable_kinds": None,
            },
        },
        "mutable_avatar": True,
        "has_heuristic": False,
    },

    "flag_adventure": {
        "game_module": "flag_adventure",
        "mutable_layers": {
            # Rocks, wood, crates, pickups (torch/pickaxe), portals can be repositioned
            "objects": {
                "format": "sparse",
                "mutable_kinds": ["rock", "wood", "metal_crate", "torch", "pickaxe"],
            },
            # Flag target can be repositioned
            "markers": {
                "format": "sparse",
                "mutable_kinds": ["flag"],
            },
            # Water cells can be swapped with each other (dense or sparse ground)
            "ground": {
                "format": "sparse",
                "mutable_kinds": ["water"],
            },
        },
        "mutable_avatar": True,
        "has_heuristic": True,
    },

    "flood_colors": {
        # No solver registered yet; listed for documentation purposes
        "game_module": None,
        "mutable_layers": {
            "objects": {
                "format": "dense",
                "mutable_kinds": None,  # all colour cell kinds
            },
        },
        "mutable_avatar": False,
        "has_heuristic": False,
    },
}
