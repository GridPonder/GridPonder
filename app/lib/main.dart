import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'src/screens/library_screen.dart';
import 'src/services/pack_registry.dart';
import 'src/services/settings_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (!kIsWeb) {
    await SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  }
  final settings = await SettingsService.create();
  final registry = await PackRegistry.create();
  runApp(GridPonderApp(settings: settings, registry: registry));
}

class GridPonderApp extends StatelessWidget {
  final SettingsService settings;
  final PackRegistry registry;

  const GridPonderApp({
    super.key,
    required this.settings,
    required this.registry,
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
      home: LibraryScreen(settings: settings, registry: registry),
    );
  }
}
