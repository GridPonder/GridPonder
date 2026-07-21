import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/services/pack_file_reader.dart';

void main() {
  test('bundled pack asset base follows its configured root', () {
    expect(BundledPackFileReader('public').assetBase, 'assets/packs/public');
    expect(
      BundledPackFileReader(
        'private',
        assetRoot: 'assets/packs-private',
      ).assetBase,
      'assets/packs-private/private',
    );
  });
}
