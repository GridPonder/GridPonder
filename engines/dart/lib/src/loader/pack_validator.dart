import 'loaded_pack.dart';

class ValidationError {
  final String field;
  final String message;
  const ValidationError(this.field, this.message);
  @override
  String toString() => '[$field] $message';
}

/// Validates a loaded pack for structural integrity.
class PackValidator {
  static List<ValidationError> validate(LoadedPack pack) {
    final errors = <ValidationError>[];
    final game = pack.game;

    // Check DSL version
    if (!pack.manifest.dslVersion.startsWith('0.')) {
      errors.add(const ValidationError(
          'manifest.dslVersion', 'Engine supports DSL v0.x only'));
    }

    // Check all level sequence refs resolve
    for (final entry in game.levelSequence) {
      if (entry.type == 'level' && entry.ref != null) {
        if (!pack.levels.containsKey(entry.ref)) {
          errors.add(ValidationError(
              'game.levelSequence', 'Level ${entry.ref} not found in pack'));
        }
      }
    }

    // Check entity kind references in levels
    for (final level in pack.levels.values) {
      // Check goals reference known entity kinds
      for (final goal in level.goals) {
        if (goal.type == 'reach_target') {
          final targetKind = goal.config['targetKind'] as String?;
          if (targetKind != null && !game.entityKinds.containsKey(targetKind)) {
            errors.add(ValidationError(
                'level.${level.id}.goals',
                'Unknown targetKind: $targetKind'));
          }
        }
      }

      // Check system IDs in overrides exist
      for (final sysId in level.systemOverrides.keys) {
        if (game.getSystem(sysId) == null) {
          errors.add(ValidationError(
              'level.${level.id}.systemOverrides',
              'Unknown system id: $sysId'));
        }
      }
    }

    return errors;
  }
}
