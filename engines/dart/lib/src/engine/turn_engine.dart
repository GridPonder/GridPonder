import 'phase_runner.dart';
import 'turn_result.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/level_definition.dart';

/// The main engine API. Manages state, history, and delegates to PhaseRunner.
class TurnEngine {
  final GameDefinition game;
  final LevelDefinition level;

  late LevelState _state;
  final List<LevelState> _history = [];
  late PhaseRunner _runner;

  TurnEngine(this.game, this.level) {
    _state = level.initialState();
    _runner = PhaseRunner(game, level);
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
    } else {
      _history.removeLast(); // nothing changed, discard undo entry
    }

    return result;
  }

  /// Undo the last action.
  bool undo() {
    if (_history.isEmpty) return false;
    _state = _history.removeLast();
    return true;
  }

  /// Reset to initial level state.
  void reset() {
    _history.clear();
    _state = level.initialState();
  }

  /// How many undo steps are available.
  int get undoDepth => _history.length;
}
