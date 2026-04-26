# GridPonder

See `README.md` for repo structure, `docs/gridponder_platform_overview.md` for architecture, and `docs/dsl/` for the full DSL spec.

## Architecture choices

- `packs/` contains multiple games which adhere to the DSL spec in `docs/dsl/`; we follow the philosophy of "each game is a folder" i.e. a DSL compliant engine can take a pack folder and render a 2D grid puzzle game
- `app/assets/packs` is a symlink to `../../packs` for Flutter integration 
- `engines/dart/` is a pure Dart package with no Flutter dependency; `engines/python/` is the Python port used by the solver and benchmark tools.
- `app/` depends on `engines/dart/` via a local path reference in `pubspec.yaml`.

## Instructions

- use skills to test levels when needed before declaring that your work is done (usually involves writing an integration test and running solvers or for fresh features starting the app and taking screenshots)
- avoid game-specific engine changes; instead check whether a feature can be supported by the current DSL and, if not, extend the DSL generically (such that re-use of the abstract same idea in other games is possible)
- do not blindly commit without giving the user a chance to test changes
- do not declare AI models as co-author in git commits
- when you place hint stops in levels, bias them towards earlier steps in the gold path and after critical/useful actions
- write screenshots or other temporary files to tmp/ (in this repo) as writing elsewhere needs explicit approval
- there is a Dart engine and a Python solver; to compare them step-by-step use trace_path.py and trace.dart and compare their outputs
- versioning: DSL version is the single source of truth in `docs/dsl/VERSION` (currently `0.5`). Engines use SemVer `MAJOR.DSL_MINOR.PATCH` (e.g. `0.5.1`). When bumping the DSL version: update `docs/dsl/VERSION`, `engines/dart/pubspec.yaml` version, and `engines/python/__init__.py __version__`. Only update `dslVersion`/`minEngineVersion` in a pack's `manifest.json` if that pack actually uses the new DSL feature — packs that don't rely on newly added systems or rules can stay at the previous version.
- after any change to engine logic, run `python engines/python/test_gold_paths.py` (Python gold paths) to verify Dart and Python engines remain in sync
- level JSON formatting: board entries and gold path moves one-per-line compact objects e.g. `{"position": [3, 2], "kind": "rock"}`; short arrays inline `[7, 7]`; see create-level skill §5 for full rules
