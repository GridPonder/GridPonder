import 'package:flutter/material.dart';
import '../services/pack_registry.dart';
import '../services/pack_service.dart';
import '../services/progress_service.dart';
import '../services/settings_service.dart';
import 'manage_packs_sheet.dart';
import 'play_screen.dart';
import 'settings_screen.dart';

enum _PackGroup { inProgress, notStarted, completed }

class LibraryScreen extends StatefulWidget {
  final SettingsService settings;
  final PackRegistry registry;
  final ProgressService progress;

  const LibraryScreen({
    super.key,
    required this.settings,
    required this.registry,
    required this.progress,
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

  _PackGroup _classify(PackInfo info) {
    final ids = info.levelIds;
    if (ids.isEmpty) return _PackGroup.notStarted;
    final done = widget.progress.completedCount(ids);
    if (done >= ids.length) return _PackGroup.completed;
    if (done > 0) return _PackGroup.inProgress;
    return _PackGroup.notStarted;
  }

  Widget _packCard(PackEntry entry, PackInfo info) => _PackCard(
        entry: entry,
        info: info,
        settings: widget.settings,
        progress: widget.progress,
      );

  static const _gridDelegate = SliverGridDelegateWithFixedCrossAxisCount(
    crossAxisCount: 2,
    crossAxisSpacing: 12,
    mainAxisSpacing: 12,
    childAspectRatio: 1.1,
  );

  Widget _flatGrid(List<(PackEntry, PackInfo)> packs) => GridView.builder(
        padding: const EdgeInsets.symmetric(horizontal: 16)
            .copyWith(top: 12, bottom: 16),
        gridDelegate: _gridDelegate,
        itemCount: packs.length,
        itemBuilder: (_, i) => _packCard(packs[i].$1, packs[i].$2),
      );

  Widget _groupedList(List<(PackEntry, PackInfo)> packs) {
    final groups = {
      _PackGroup.inProgress: <(PackEntry, PackInfo)>[],
      _PackGroup.notStarted: <(PackEntry, PackInfo)>[],
      _PackGroup.completed: <(PackEntry, PackInfo)>[],
    };
    for (final p in packs) {
      groups[_classify(p.$2)]!.add(p);
    }

    Widget section(String label, List<(PackEntry, PackInfo)> items) {
      if (items.isEmpty) return const SizedBox.shrink();
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: Text(
              label,
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: Colors.black45,
                letterSpacing: 0.6,
              ),
            ),
          ),
          GridView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            gridDelegate: _gridDelegate,
            itemCount: items.length,
            itemBuilder: (_, i) => _packCard(items[i].$1, items[i].$2),
          ),
        ],
      );
    }

    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        section('In Progress', groups[_PackGroup.inProgress]!),
        section('More Games', groups[_PackGroup.notStarted]!),
        section('Play Again', groups[_PackGroup.completed]!),
      ],
    );
  }

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
                  if (widget.progress.isDeveloperMode) {
                    return _flatGrid(packs);
                  }
                  return _groupedList(packs);
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
              'assets/packs/gridponder-base/sprites/tiles/rabbit_idea_grid_medium_resolution.png',
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
  final ProgressService progress;

  const _PackCard({
    required this.entry,
    required this.info,
    required this.settings,
    required this.progress,
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
      final startId = widget.progress?.firstIncompleteRef(pack.sequence);
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => PlayScreen(
            packService: pack,
            settings: widget.settings,
            progress: widget.progress,
            startLevelId: startId,
          ),
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
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      coverImage != null
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
                      _buildCoverBadge(base),
                    ],
                  ),
                ),
              ),
              _buildProgressFooter(base),
            ],
          ),
        ),
      ),
    );
  }

  /// Small badge overlaid on the top-right of the cover image.
  /// Shows "DEV" in dev mode, or "done\ntotal" in normal mode.
  Widget _buildCoverBadge(Color baseColor) {
    final levelIds = widget.info.levelIds;
    final isDev = widget.progress.isDeveloperMode;

    if (isDev) {
      return Positioned(
        top: 4,
        right: 0,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
          decoration: BoxDecoration(
            color: Colors.orange.shade300.withOpacity(0.92),
            borderRadius: BorderRadius.circular(5),
          ),
          child: const Text(
            'DEV',
            style: TextStyle(
                fontSize: 8, fontWeight: FontWeight.bold, color: Colors.white),
          ),
        ),
      );
    }

    if (levelIds.isEmpty) return const SizedBox.shrink();

    final total = levelIds.length;
    final done = widget.progress.completedCount(levelIds);
    final complete = done == total;
    final badgeColor = complete
        ? Colors.green.shade600.withOpacity(0.90)
        : Colors.black.withOpacity(0.45);

    return Positioned(
      top: 4,
      right: 0,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 3),
        decoration: BoxDecoration(
          color: badgeColor,
          borderRadius: BorderRadius.circular(5),
        ),
        child: Text(
          '$done\n/$total',
          textAlign: TextAlign.center,
          style: const TextStyle(
              fontSize: 8,
              fontWeight: FontWeight.bold,
              color: Colors.white,
              height: 1.2),
        ),
      ),
    );
  }

  Widget _buildProgressFooter(Color baseColor) {
    final levelIds = widget.info.levelIds;

    // Description at full width; progress bar below if levels are known.
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(10, 2, 10, 4),
          child: Text(
            widget.info.tagline,
            style: const TextStyle(color: Colors.black54, fontSize: 10),
            textAlign: TextAlign.center,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ),
        if (levelIds.isNotEmpty && !widget.progress.isDeveloperMode)
          ClipRRect(
            borderRadius: const BorderRadius.only(
              bottomLeft: Radius.circular(16),
              bottomRight: Radius.circular(16),
            ),
            child: LinearProgressIndicator(
              value: widget.progress.completedCount(levelIds) / levelIds.length,
              minHeight: 4,
              backgroundColor: Colors.black12,
              valueColor: AlwaysStoppedAnimation<Color>(
                  Color.lerp(baseColor, Colors.black, 0.3)!),
            ),
          )
        else
          const SizedBox(height: 6),
      ],
    );
  }
}
