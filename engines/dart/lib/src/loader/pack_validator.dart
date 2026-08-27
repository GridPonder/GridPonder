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
  static final RegExp _tagPattern =
      RegExp(r'^[a-z0-9]+(?:-[a-z0-9]+)*$');

  static List<ValidationError> validate(LoadedPack pack) {
    final errors = <ValidationError>[];
    final game = pack.game;

    // Check DSL version
    if (!pack.manifest.dslVersion.startsWith('0.')) {
      errors.add(const ValidationError(
          'manifest.dslVersion', 'Engine supports DSL v0.x only'));
    }

    if (pack.manifest.tags.length > 12) {
      errors.add(const ValidationError(
          'manifest.tags', 'A pack may declare at most 12 game tags'));
    }
    if (pack.manifest.tags.toSet().length != pack.manifest.tags.length) {
      errors.add(const ValidationError(
          'manifest.tags', 'Game tags must be unique'));
    }
    for (final tag in pack.manifest.tags) {
      if (tag.length > 48 || !_tagPattern.hasMatch(tag)) {
        errors.add(ValidationError(
            'manifest.tags',
            'Invalid game tag "$tag"; use lowercase kebab-case with at most '
                '48 characters'));
      }
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
