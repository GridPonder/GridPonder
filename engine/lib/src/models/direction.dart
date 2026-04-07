import 'position.dart';

/// Eight-directional movement.
enum Direction {
  up,
  down,
  left,
  right,
  upLeft,
  upRight,
  downLeft,
  downRight;

  static Direction fromJson(String s) {
    switch (s) {
      case 'up': return Direction.up;
      case 'down': return Direction.down;
      case 'left': return Direction.left;
      case 'right': return Direction.right;
      case 'up_left': return Direction.upLeft;
      case 'up_right': return Direction.upRight;
      case 'down_left': return Direction.downLeft;
      case 'down_right': return Direction.downRight;
      default: throw FormatException('Unknown direction: $s');
    }
  }

  String toJson() {
    switch (this) {
      case Direction.up: return 'up';
      case Direction.down: return 'down';
      case Direction.left: return 'left';
      case Direction.right: return 'right';
      case Direction.upLeft: return 'up_left';
      case Direction.upRight: return 'up_right';
      case Direction.downLeft: return 'down_left';
      case Direction.downRight: return 'down_right';
    }
  }

  Position get offset {
    switch (this) {
      case Direction.up: return const Position(0, -1);
      case Direction.down: return const Position(0, 1);
      case Direction.left: return const Position(-1, 0);
      case Direction.right: return const Position(1, 0);
      case Direction.upLeft: return const Position(-1, -1);
      case Direction.upRight: return const Position(1, -1);
      case Direction.downLeft: return const Position(-1, 1);
      case Direction.downRight: return const Position(1, 1);
    }
  }

  Direction get opposite {
    switch (this) {
      case Direction.up: return Direction.down;
      case Direction.down: return Direction.up;
      case Direction.left: return Direction.right;
      case Direction.right: return Direction.left;
      case Direction.upLeft: return Direction.downRight;
      case Direction.upRight: return Direction.downLeft;
      case Direction.downLeft: return Direction.upRight;
      case Direction.downRight: return Direction.upLeft;
    }
  }

  bool get isCardinal =>
      this == up || this == down || this == left || this == right;

  bool get isDiagonal => !isCardinal;
}
