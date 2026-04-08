# GridPonder

See `README.md` for repo structure, `docs/gridponder_platform_overview.md` for architecture, and `docs/dsl/` for the full DSL spec.

## Architecture choices

- `packs/` contains multiple games which adhere to the DSL spec in `docs/dsl/`; we follow the philosophy of "each game is a folder" i.e. a DSL compliant engine can take a pack folder and render a 2D grid puzzle game
- `app/assets/packs` is a symlink to `../../packs` for Flutter integration 
- `engine/` is a pure Dart package with no Flutter dependency.
- `app/` depends on `engine/` via a local path reference in `pubspec.yaml`.

## Instructions

- use skills to test levels when needed before declaring that your work is done (usually involves writing an integration test, starting the app, taking screenshots and analysing correctness)
- do not declare AI models as co-author in git commits
- when you place hint stops in levels, bias them towards earlier steps in the gold path and after critical/useful actions
