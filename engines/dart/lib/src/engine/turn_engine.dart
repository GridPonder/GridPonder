import 'phase_runner.dart';
import 'turn_result.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/level_definition.dart';
import '../rules/rules_engine.dart';
import '../systems/system_registry.dart';

/// The main engine API. Manages state, history, and delegates to PhaseRunner.
class TurnEngine {
  final GameDefinition game;
  final LevelDefinition level;

  late LevelState _state;
  final List<LevelState> _history = [];
  final List<GameAction> _actionHistory = [];
  late PhaseRunner _runner;

  TurnEngine(this.game, this.level) {
    _state = level.initialState();
    _runner = PhaseRunner(game, level);
    _applyLoadCascade();
  }

  LevelState get state => _state;

  bool get isWon => _state.isWon;
  bool get isLost => _state.isLost;

  /// Execute one player action. Returns the turn result.
  /// If the action is rejected, the state is unchanged.
  TurnResult executeTurn(GameAction action) {
    if (_state.isWon || _state.isLost) {
      return TurnResult.rejected(_state);
    }

    // Save state for undo before mutating
    _history.add(_state.copy());

    // Run the turn on a working copy (PhaseRunner mutates state in place)
    final workingState = _state.copy();
    final result = _runner.run(action, workingState);

    if (result.accepted) {
      _state = result.newState;
      _actionHistory.add(action);
    } else {
      _history.removeLast(); // nothing changed, discard undo entry
    }

    return result;
  }

  /// Undo the last action.
  bool undo() {
    if (_history.isEmpty) return false;
    _state = _history.removeLast();
    if (_actionHistory.isNotEmpty) _actionHistory.removeLast();
    return true;
  }

  /// Reset to initial level state.
  void reset() {
    _history.clear();
    _actionHistory.clear();
    _state = level.initialState();
    _applyLoadCascade();
  }

  /// Fire `object_placed` events for every object on a non-ground layer at
  /// level load, then run the rules engine cascade. This makes "always-on"
  /// rules like `crate_floats_on_water` apply uniformly to objects placed
  /// during play and to objects already on the board at start, so the player
  /// sees consistent behaviour regardless of how an object came to be there.
  void _applyLoadCascade() {
    final initialEvents = <GameEvent>[];
    for (final layerDef in game.layers) {
      // Only synthesize for object-style layers (zero_or_one). Ground layers
      // (exactly_one) describe terrain, not placed objects.
      if (layerDef.occupancy != 'zero_or_one') continue;
      final layer = _state.board.layers[layerDef.id];
      if (layer == null) continue;
      for (final entry in layer.entries()) {
        initialEvents.add(GameEvent.objectPlaced(
            entry.key, entry.value.kind, entry.value.params));
      }
    }
    if (initialEvents.isEmpty) return;
    final systems = SystemRegistry.instantiate(game, level.systemOverrides);
    final rulesEngine = RulesEngine(game.rules, level.rules);
    rulesEngine.evaluate(
        initialEvents, _state, game, game.defaults.maxCascadeDepth, systems);
  }

  /// How many undo steps are available.
  int get undoDepth => _history.length;

  /// All accepted actions in order (supports undo).
  List<GameAction> get actionHistory => List.unmodifiable(_actionHistory);
}
