import 'package:flutter/material.dart';
import '../services/pack_registry.dart';
import '../services/pack_service.dart';
import '../services/settings_service.dart';
import 'manage_packs_sheet.dart';
import 'play_screen.dart';
import 'settings_screen.dart';

class LibraryScreen extends StatefulWidget {
  final SettingsService settings;
  final PackRegistry registry;

  const LibraryScreen({
    super.key,
    required this.settings,
    required this.registry,
  });

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  late Future<List<(PackEntry, PackInfo)>> _packsFuture;

  @override
  void initState() {
    super.initState();
    _packsFuture = _loadPacks();
  }

  Future<List<(PackEntry, PackInfo)>> _loadPacks() async {
    final entries = await widget.registry.listAll();
    return Future.wait(
      entries.map((e) async {
        final info = await PackService.loadInfoFromEntry(e);
        return (e, info);
      }),
    );
  }

  void _refresh() => setState(() => _packsFuture = _loadPacks());

  void _openManagePacks() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => ManagePacksSheet(
        registry: widget.registry,
        onChanged: _refresh,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF5F0E8),
      body: SafeArea(
        child: Column(
          children: [
            _Header(
              settings: widget.settings,
              onManagePacks: _openManagePacks,
            ),
            Expanded(
              child: FutureBuilder<List<(PackEntry, PackInfo)>>(
                future: _packsFuture,
                builder: (context, snap) {
                  final packs = snap.data ?? [];
                  if (snap.connectionState == ConnectionState.waiting &&
                      packs.isEmpty) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  return GridView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 16)
                        .copyWith(top: 12, bottom: 16),
                    gridDelegate:
                        const SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 2,
                      crossAxisSpacing: 12,
                      mainAxisSpacing: 12,
                      childAspectRatio: 1.1,
                    ),
                    itemCount: packs.length,
                    itemBuilder: (context, i) {
                      final (entry, info) = packs[i];
                      return _PackCard(
                        entry: entry,
                        info: info,
                        settings: widget.settings,
                      );
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------

class _Header extends StatelessWidget {
  final SettingsService settings;
  final VoidCallback onManagePacks;

  const _Header({required this.settings, required this.onManagePacks});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.08),
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Row(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: Image.asset(
              'assets/packs/rabbit-character/sprites/avatar/rabbit_idea_grid_medium_resolution.png',
              width: 48,
              height: 48,
              fit: BoxFit.cover,
            ),
          ),
          const SizedBox(width: 14),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'GridPonder',
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                    color: Colors.black87,
                  ),
                ),
                Text(
                  'grid puzzle adventures',
                  style: TextStyle(
                    fontSize: 13,
                    color: Colors.grey,
                  ),
                ),
              ],
            ),
          ),
          IconButton(
            icon: Icon(Icons.inventory_2_outlined,
                color: Colors.grey.shade600),
            tooltip: 'Manage Packs',
            onPressed: onManagePacks,
          ),
          IconButton(
            icon: Icon(Icons.help_outline, color: Colors.grey.shade600),
            onPressed: () => _showHelp(context),
          ),
          IconButton(
            icon: Icon(Icons.settings_outlined, color: Colors.grey.shade600),
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(
                  builder: (_) => SettingsScreen(settings: settings)),
            ),
          ),
        ],
      ),
    );
  }

  void _showHelp(BuildContext context) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            Icon(Icons.help_outline,
                color: Theme.of(context).primaryColor, size: 26),
            const SizedBox(width: 10),
            const Text('How to Play',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          ],
        ),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              _helpSection('🎯 Goal',
                  'Each pack has unique mechanics. Pick a pack from the library and work through its levels.'),
              const SizedBox(height: 14),
              _helpSection('👆 Controls',
                  '• Swipe on the board to move your character\n'
                  '• Diagonal swipes work in packs that support them\n'
                  '• Use the action buttons below the board for special moves'),
              const SizedBox(height: 14),
              _helpSection('↩️ Undo & Reset',
                  '• Tap Undo to take back the last move\n'
                  '• Long-press Undo to reset the level entirely'),
              const SizedBox(height: 14),
              _helpSection('🤖 AI Play',
                  'Enable AI Play in Settings to watch an agent solve levels. '
                  'Choose between a random agent or an LLM (requires Anthropic API key).'),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text('Got it!',
                style: TextStyle(
                    color: Theme.of(context).primaryColor,
                    fontWeight: FontWeight.w600)),
          ),
        ],
      ),
    );
  }

  Widget _helpSection(String title, String body) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title,
            style: const TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w600,
                color: Colors.black87)),
        const SizedBox(height: 6),
        Text(body,
            style: TextStyle(
                fontSize: 13, color: Colors.grey.shade700, height: 1.4)),
      ],
    );
  }
}

// ---------------------------------------------------------------------------

class _PackCard extends StatefulWidget {
  final PackEntry entry;
  final PackInfo info;
  final SettingsService settings;

  const _PackCard({
    required this.entry,
    required this.info,
    required this.settings,
  });

  @override
  State<_PackCard> createState() => _PackCardState();
}

class _PackCardState extends State<_PackCard> {
  bool _loading = false;

  Future<void> _open() async {
    if (_loading) return;
    setState(() => _loading = true);
    try {
      final pack = await PackService.loadFromEntry(widget.entry);
      if (!mounted) return;
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) =>
              PlayScreen(packService: pack, settings: widget.settings),
        ),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content:
                  Text('Failed to load ${widget.info.title}: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final base = Color(widget.info.color);
    final color = Color.lerp(base, Colors.white, 0.45)!;
    final coverImage = widget.info.coverImage;

    return GestureDetector(
      onTap: _open,
      child: Container(
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(16),
          boxShadow: [
            BoxShadow(
              color: base.withOpacity(0.2),
              blurRadius: 8,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(10, 6, 10, 2),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        widget.info.title,
                        style: const TextStyle(
                          color: Colors.black87,
                          fontWeight: FontWeight.bold,
                          fontSize: 13,
                        ),
                        textAlign: TextAlign.center,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    if (_loading)
                      const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.black38),
                      ),
                  ],
                ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  child: coverImage != null
                      ? Image(
                          image: coverImage,
                          fit: BoxFit.contain,
                          errorBuilder: (_, __, ___) => Center(
                            child: Icon(Icons.grid_view,
                                color: Colors.black26, size: 36),
                          ),
                        )
                      : Center(
                          child: Icon(Icons.grid_view,
                              color: Colors.black26, size: 36),
                        ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(10, 2, 10, 8),
                child: Text(
                  widget.info.description,
                  style: const TextStyle(
                    color: Colors.black54,
                    fontSize: 10,
                  ),
                  textAlign: TextAlign.center,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
