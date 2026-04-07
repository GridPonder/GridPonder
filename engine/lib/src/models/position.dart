import 'direction.dart';

/// Immutable 2D grid position.
class Position {
  final int x;
  final int y;

  const Position(this.x, this.y);

  factory Position.fromJson(dynamic json) {
    if (json is List) return Position(json[0] as int, json[1] as int);
    throw FormatException('Expected [x, y] array, got $json');
  }

  List<int> toJson() => [x, y];

  bool isValid(int width, int height) =>
      x >= 0 && y >= 0 && x < width && y < height;

  Position operator +(Position other) => Position(x + other.x, y + other.y);
  Position operator -(Position other) => Position(x - other.x, y - other.y);

  Position moved(Direction dir) => this + dir.offset;

  @override
  bool operator ==(Object other) =>
      other is Position && other.x == x && other.y == y;

  @override
  int get hashCode => Object.hash(x, y);

  @override
  String toString() => '($x, $y)';
}
