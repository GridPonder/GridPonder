// Unit tests for bundled-pack discovery. `PackRegistry.resolveBundledRoots`
// is a pure function over AssetManifest keys, so these tests don't need a
// fake asset bundle.
import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/services/pack_file_reader.dart';
import 'package:gridponder_app/src/services/pack_registry.dart';

void main() {
  group('PackRegistry.resolveBundledRoots', () {
    test('discovers keys from both roots with correct (root, id) attribution',
        () {
      final roots = PackRegistry.resolveBundledRoots([
        'assets/packs/sokoban/manifest.json',
        'assets/packs-private/dev_game/manifest.json',
      ]);

      expect(roots, {
        'dev_game': 'assets/packs-private',
        'sokoban': 'assets/packs',
      });
    });

    test('a pack id present under both roots dedupes with assets/packs winning',
        () {
      final roots = PackRegistry.resolveBundledRoots([
        'assets/packs-private/shared/manifest.json',
        'assets/packs/shared/manifest.json',
      ]);

      expect(roots['shared'], 'assets/packs');
      expect(roots.length, 1);
    });

    test('result is sorted by id', () {
      final roots = PackRegistry.resolveBundledRoots([
        'assets/packs/zeta/manifest.json',
        'assets/packs-private/alpha/manifest.json',
        'assets/packs/mid/manifest.json',
      ]);

      expect(roots.keys.toList(), ['alpha', 'mid', 'zeta']);
    });

    test('ignores non-manifest keys and deeper paths', () {
      final roots = PackRegistry.resolveBundledRoots([
        'assets/packs/x/levels/manifest.json', // depth-2 — must not count
        'assets/packs/x/theme.json', // not a manifest at all
        'assets/packs/y/manifest.json', // valid depth-1 manifest
      ]);

      expect(roots, {'y': 'assets/packs'});
    });

    test('returns an empty map for no matching keys', () {
      final roots = PackRegistry.resolveBundledRoots(
        ['assets/fonts/roboto.ttf', 'AssetManifest.json'],
      );

      expect(roots, isEmpty);
    });
  });

  group('BundledPackFileReader.assetBase', () {
    test('defaults to the assets/packs root', () {
      expect(BundledPackFileReader('x').assetBase, 'assets/packs/x');
    });

    test('honours an explicit assetRoot', () {
      expect(
        BundledPackFileReader('x', assetRoot: 'assets/packs-private')
            .assetBase,
        'assets/packs-private/x',
      );
    });
  });
}
