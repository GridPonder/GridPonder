import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'src/screens/library_screen.dart';
import 'src/services/settings_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  final settings = await SettingsService.create();
  runApp(GridPonderApp(settings: settings));
}

class GridPonderApp extends StatelessWidget {
  final SettingsService settings;

  const GridPonderApp({super.key, required this.settings});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'GridPonder',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF2196F3)),
        useMaterial3: true,
      ),
      home: LibraryScreen(settings: settings),
    );
  }
}
