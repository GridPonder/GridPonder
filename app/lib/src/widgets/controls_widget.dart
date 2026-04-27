import 'dart:math' show pi;
import 'package:flutter/material.dart';
import 'package:gridponder_engine/engine.dart';
import '../services/hint_service.dart';
import 'board_renderer.dart' show cellNamedColor;

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
  final VoidCallback? onSolve;
  final bool canUndo;
  final GameDefinition game;
  final List<HintStatus> hintStatuses;
  /// If non-null, only these action IDs are currently applicable.
  /// Others are rendered grayed out (but still tappable — engine rejects them).
  final Set<String>? availableActionIds;

  const ControlsWidget({
    super.key,
    required this.onAction,
    required this.onUndo,
    required this.onReset,
    required this.onExit,
    this.onHint,
    this.onSolve,
    required this.canUndo,
    required this.game,
    this.hintStatuses = const [],
    this.availableActionIds,
  });

  @override
  State<ControlsWidget> createState() => _ControlsWidgetState();
}

class _ControlsWidgetState extends State<ControlsWidget> {
  List<ActionDef> get _buttonActions => widget.game.actions
      .where((a) => a.id != 'move' && a.id != 'diagonal_swap')
      .toList();

  bool get _hasDiagonalSwap =>
      widget.game.actions.any((a) => a.id == 'diagonal_swap');

  @override
  Widget build(BuildContext context) {
    final actions = _buttonActions.map((a) => _actionButton(a)).toList();
    final controls = Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (widget.hintStatuses.isNotEmpty)
          _HintBtn(statuses: widget.hintStatuses, onTap: widget.onHint),
        if (widget.onSolve != null)
          _CtrlBtn(
            icon: Icons.skip_next,
            label: 'Solve',
            onTap: widget.onSolve,
          ),
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

    final diagBtns = _hasDiagonalSwap
        ? _DiagonalSwapBtns(
            onTap: (dir) =>
                widget.onAction(GameAction('diagonal_swap', {'direction': dir})),
          )
        : null;

    if (actions.isEmpty && diagBtns == null) return controls;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (diagBtns != null) ...[diagBtns, const SizedBox(height: 6)],
        if (actions.isNotEmpty) ...[
          Wrap(
            alignment: WrapAlignment.center,
            spacing: 6,
            runSpacing: 6,
            children: actions,
          ),
          const SizedBox(height: 6),
        ],
        controls,
      ],
    );
  }

  Widget _actionButton(ActionDef actionDef) {
    if (actionDef.params.isEmpty) {
      // Colour-flood actions: "flood_red", "flood_blue", etc.
      if (actionDef.id.startsWith('flood_')) {
        final colorName = actionDef.id.substring(6); // e.g. "red"
        final color = _floodColor(colorName);
        final available = widget.availableActionIds == null ||
            widget.availableActionIds!.contains(actionDef.id);
        return _ColorBtn(
          color: color,
          available: available,
          onTap: () => widget.onAction(GameAction(actionDef.id, {})),
        );
      }

      final icon = switch (actionDef.id) {
        'rotate' => Icons.rotate_right,
        'flip' => Icons.flip,
        'clone' => Icons.blur_on,
        _ => Icons.play_arrow_outlined,
      };
      final label = switch (actionDef.id) {
        'rotate' => 'Rotate',
        'flip' => 'Flip',
        'clone' => 'Clone',
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

  /// Map a colour name (e.g. "red") to a display Color.
  Color _floodColor(String name) => cellNamedColor(name);
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

/// Coloured drop button for flood_<colour> actions.
/// Uses a pill shape matching the other control buttons, with a water-drop
/// icon tinted in the flood colour — works well both available and grayed.
class _ColorBtn extends StatelessWidget {
  final Color color;
  final bool available;
  final VoidCallback onTap;

  const _ColorBtn({required this.color, required this.available, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final fg = available ? color : color.withAlpha(80);
    final bg = available ? color.withAlpha(30) : Colors.grey.shade100;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 14),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(8),
          border: available
              ? Border.all(color: color.withAlpha(120), width: 1.5)
              : Border.all(color: Colors.grey.shade300),
        ),
        child: Icon(Icons.water_drop, size: 22, color: fg),
      ),
    );
  }
}

// ---------------------------------------------------------------------------

/// Two diagonal-swap buttons: one per distinct diagonal of the 2×2 overlay.
/// up_left  (↖) swaps top-left ↔ bottom-right (the "\" diagonal).
/// up_right (↗) swaps top-right ↔ bottom-left (the "/" diagonal).
class _DiagonalSwapBtns extends StatelessWidget {
  final void Function(String direction) onTap;
  const _DiagonalSwapBtns({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _diagBtn('up_left',  -3 * pi / 4), // ↖  top-left ↔ bottom-right
        const SizedBox(width: 10),
        _diagBtn('up_right', -pi / 4),     // ↗  top-right ↔ bottom-left
      ],
    );
  }

  Widget _diagBtn(String direction, double angle) {
    return GestureDetector(
      onTap: () => onTap(direction),
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: 8),
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 20),
        decoration: BoxDecoration(
          color: Colors.grey.shade200,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Transform.rotate(
              angle: angle,
              child: Icon(Icons.arrow_forward,
                  size: 22, color: Colors.grey.shade700),
            ),
            const SizedBox(height: 2),
            Text(
              'Swap',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w500,
                color: Colors.grey.shade700,
              ),
            ),
          ],
        ),
      ),
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
