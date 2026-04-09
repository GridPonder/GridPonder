import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'src/screens/library_screen.dart';
import 'src/services/pack_registry.dart';
import 'src/services/progress_service.dart';
import 'src/services/settings_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (!kIsWeb) {
    await SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  }
  final settings = await SettingsService.create();
  final registry = await PackRegistry.create();
  final progress = await ProgressService.create();
  runApp(GridPonderApp(settings: settings, registry: registry, progress: progress));
}

class GridPonderApp extends StatelessWidget {
  final SettingsService settings;
  final PackRegistry registry;
  final ProgressService progress;

  const GridPonderApp({
    super.key,
    required this.settings,
    required this.registry,
    required this.progress,
  });

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'GridPonder',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF2196F3)),
        useMaterial3: true,
      ),
      home: LibraryScreen(
        settings: settings,
        registry: registry,
        progress: progress,
      ),
    );
  }
}
