/// Pack manifest — entry point of a game pack.
class PackManifest {
  final String dslVersion;
  final int packVersion;
  final String gameId;
  final String title;
  final String version;
  final String minEngineVersion;
  final String? author;
  final String? description;
  final String gameFile;
  final String levelDirectory;
  final String assetsDirectory;
  final String? coverImage;
  final String? license;
  final String? website;
  final List<String> sharedAssets;

  const PackManifest({
    required this.dslVersion,
    required this.packVersion,
    required this.gameId,
    required this.title,
    required this.version,
    required this.minEngineVersion,
    this.author,
    this.description,
    this.gameFile = 'game.json',
    this.levelDirectory = 'levels',
    this.assetsDirectory = 'assets',
    this.coverImage,
    this.license,
    this.website,
    this.sharedAssets = const [],
  });

  factory PackManifest.fromJson(Map<String, dynamic> j) => PackManifest(
        dslVersion: j['dslVersion'] as String,
        packVersion: j['packVersion'] as int,
        gameId: j['gameId'] as String,
        title: j['title'] as String,
        version: j['version'] as String,
        minEngineVersion: j['minEngineVersion'] as String,
        author: j['author'] as String?,
        description: j['description'] as String?,
        gameFile: (j['gameFile'] as String?) ?? 'game.json',
        levelDirectory: (j['levelDirectory'] as String?) ?? 'levels',
        assetsDirectory: (j['assetsDirectory'] as String?) ?? 'assets',
        coverImage: j['coverImage'] as String?,
        license: j['license'] as String?,
        website: j['website'] as String?,
        sharedAssets: j['sharedAssets'] != null
            ? List<String>.from(j['sharedAssets'] as List)
            : const [],
      );
}
