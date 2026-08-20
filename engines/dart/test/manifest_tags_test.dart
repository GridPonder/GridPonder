import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

void main() {
  PackManifest manifestWith(List<String> tags) => PackManifest(
        dslVersion: '0.7',
        packVersion: 1,
        gameId: 'test',
        title: 'Test',
        version: '1.0.0',
        minEngineVersion: '0.7.0',
        tags: tags,
      );

  LoadedPack loadedWith(List<String> tags) => LoadedPack(
        manifest: manifestWith(tags),
        game: const GameDefinition(
          id: 'test',
          title: 'Test',
          layers: [],
          actions: [],
          entityKinds: {},
          systems: [],
          rules: [],
          levelSequence: [],
          defaults: GameDefaults(),
        ),
        levels: const {},
      );

  test('manifest parses normalized game tags', () {
    final manifest = PackManifest.fromJson({
      'dslVersion': '0.7',
      'packVersion': 1,
      'gameId': 'test',
      'title': 'Test',
      'version': '1.0.0',
      'minEngineVersion': '0.7.0',
      'tags': ['routing', 'spatial-planning'],
    });
    expect(manifest.tags, ['routing', 'spatial-planning']);
  });

  test('validator rejects malformed and duplicate tags', () {
    final malformed = PackValidator.validate(loadedWith(['Not Normalized']));
    expect(malformed.any((error) => error.field == 'manifest.tags'), isTrue);

    final duplicate =
        PackValidator.validate(loadedWith(['routing', 'routing']));
    expect(duplicate.any((error) => error.field == 'manifest.tags'), isTrue);
  });
}
