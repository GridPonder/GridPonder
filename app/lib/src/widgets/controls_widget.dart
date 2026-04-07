import 'package:flutter/material.dart';
import 'package:gridponder_engine/engine.dart';
import '../services/hint_service.dart';

typedef ActionCallback = void Function(GameAction action);

/// Renders the board and the action/control button row.
/// Gesture (swipe) detection is handled by the parent screen so it covers
/// the full screen area.
class ControlsWidget extends StatefulWidget {
  final ActionCallback onAction;
  final VoidCallback onUndo;
  final VoidCallback onReset;
  final VoidCallback onExit;
  final VoidCallback? onHint;
  final bool canUndo;
  final GameDefinition game;
  final List<HintStatus> hintStatuses;

  const ControlsWidget({
    super.key,
    required this.onAction,
    required this.onUndo,
    required this.onReset,
    required this.onExit,
    this.onHint,
    required this.canUndo,
    required this.game,
    this.hintStatuses = const [],
  });

  @override
  State<ControlsWidget> createState() => _ControlsWidgetState();
}

class _ControlsWidgetState extends State<ControlsWidget> {
  List<ActionDef> get _buttonActions => widget.game.actions
      .where((a) => a.id != 'move' && a.id != 'diagonal_swap')
      .toList();

  @override
  Widget build(BuildContext context) {
    final actions = _buttonActions.map((a) => _actionButton(a)).toList();
    final controls = Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (widget.hintStatuses.isNotEmpty)
          _HintBtn(statuses: widget.hintStatuses, onTap: widget.onHint),
        _CtrlBtn(
          icon: Icons.undo,
          label: 'Undo',
          onTap: widget.canUndo ? widget.onUndo : null,
          onLongPress: widget.onReset,
        ),
        _CtrlBtn(
          icon: Icons.exit_to_app,
          label: 'Exit',
          onTap: widget.onExit,
        ),
      ],
    );

    if (actions.isEmpty) return controls;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(mainAxisAlignment: MainAxisAlignment.center, children: actions),
        const SizedBox(height: 6),
        controls,
      ],
    );
  }

  Widget _actionButton(ActionDef actionDef) {
    if (actionDef.params.isEmpty) {
      final icon = switch (actionDef.id) {
        'rotate' => Icons.rotate_right,
        'flip' => Icons.flip,
        'flood' => Icons.water_drop_outlined,
        _ => Icons.play_arrow_outlined,
      };
      final label = switch (actionDef.id) {
        'rotate' => 'Rotate',
        'flip' => 'Flip',
        'flood' => 'Flood',
        _ => actionDef.id,
      };
      return _CtrlBtn(
        icon: icon,
        label: label,
        onTap: () => widget.onAction(GameAction(actionDef.id, {})),
      );
    }
    return const SizedBox.shrink();
  }
}

// ---------------------------------------------------------------------------

class _HintBtn extends StatelessWidget {
  final List<HintStatus> statuses;
  final VoidCallback? onTap;

  const _HintBtn({required this.statuses, this.onTap});

  bool get _anyAvailable => statuses.any((s) => s.isAvailable && !s.isUsed);

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 8),
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 16),
        decoration: BoxDecoration(
          color: _anyAvailable ? Colors.blue.shade100 : Colors.grey.shade100,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.lightbulb_outline,
                  size: 20,
                  color: _anyAvailable
                      ? Colors.blue.shade700
                      : Colors.grey.shade400,
                ),
                const SizedBox(width: 4),
                ...statuses.map((s) => _dot(s)),
              ],
            ),
            const SizedBox(height: 2),
            Text(
              'Hint',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w500,
                color: _anyAvailable
                    ? Colors.blue.shade700
                    : Colors.grey.shade400,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _dot(HintStatus s) {
    final Color color;
    final IconData icon;
    if (s.isUsed) {
      color = Colors.green;
      icon = Icons.check_circle;
    } else if (s.isAvailable) {
      color = Colors.blue;
      icon = Icons.circle;
    } else {
      color = Colors.grey.shade400;
      icon = Icons.circle_outlined;
    }
    return Padding(
      padding: const EdgeInsets.only(left: 2),
      child: Icon(icon, size: 11, color: color),
    );
  }
}

// ---------------------------------------------------------------------------

class _CtrlBtn extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;

  const _CtrlBtn({
    required this.icon,
    required this.label,
    this.onTap,
    this.onLongPress,
  });

  @override
  Widget build(BuildContext context) {
    final enabled = onTap != null;
    return GestureDetector(
      onTap: onTap,
      onLongPress: onLongPress,
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 8),
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 20),
        decoration: BoxDecoration(
          color: enabled ? Colors.grey.shade200 : Colors.grey.shade100,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon,
                color:
                    enabled ? Colors.grey.shade700 : Colors.grey.shade400,
                size: 22),
            const SizedBox(height: 2),
            Text(
              label,
              style: TextStyle(
                color: enabled
                    ? Colors.grey.shade700
                    : Colors.grey.shade400,
                fontSize: 11,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
