/// GridPonder Engine — pure Dart interpreter for DSL v0.1.0 game packs.
library gridponder_engine;

// Models
export 'src/models/position.dart';
export 'src/models/direction.dart';
export 'src/models/entity.dart';
export 'src/models/layer.dart';
export 'src/models/board.dart';
export 'src/models/avatar.dart';
export 'src/models/event.dart';
export 'src/models/condition.dart';
export 'src/models/effect.dart';
export 'src/models/rule.dart';
export 'src/models/system_def.dart';
export 'src/models/goal.dart';
export 'src/models/solution.dart';
export 'src/models/game_action.dart';
export 'src/models/game_definition.dart';
export 'src/models/level_definition.dart';
export 'src/models/game_state.dart';
export 'src/models/manifest.dart';
export 'src/models/theme.dart';
export 'src/models/value_ref.dart';

// Loader
export 'src/loader/loaded_pack.dart';
export 'src/loader/pack_loader.dart';
export 'src/loader/pack_validator.dart';

// Engine
export 'src/engine/turn_engine.dart';
export 'src/engine/turn_result.dart';

// Agent
export 'src/agent/agent.dart';
export 'src/agent/text_renderer.dart';
export 'src/agent/ascii_renderer.dart'; // re-exports TextRenderer as AsciiRenderer for backwards compat
export 'src/agent/random_agent.dart';
export 'src/agent/llm_agent.dart';
