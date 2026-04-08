import 'dart:typed_data';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import '../services/pack_importer.dart';
import '../services/pack_registry.dart';
import '../services/pack_service.dart';

/// Bottom sheet for importing and deleting user-installed packs.
class ManagePacksSheet extends StatefulWidget {
  final PackRegistry registry;

  /// Called when a pack is imported or deleted so the library can refresh.
  final VoidCallback onChanged;

  const ManagePacksSheet({
    super.key,
    required this.registry,
    required this.onChanged,
  });

  @override
  State<ManagePacksSheet> createState() => _ManagePacksSheetState();
}

class _ManagePacksSheetState extends State<ManagePacksSheet> {
  late Future<List<PackInfo>> _installedFuture;
  bool _importing = false;
  String? _importError;

  @override
  void initState() {
    super.initState();
    _installedFuture = _loadInstalled();
  }

  Future<List<PackInfo>> _loadInstalled() async {
    final ids = await widget.registry.listInstalledIds();
    final infos = <PackInfo>[];
    for (final id in ids) {
      final reader = await widget.registry.storage.readerFor(id);
      if (reader != null) {
        try {
          infos.add(await PackService.loadInfoFromEntry(
            PackEntry(id: id, isInstalled: true, reader: reader),
          ));
        } catch (_) {
          // Corrupted pack — add a placeholder so it can still be deleted.
          infos.add(PackInfo(
            id: id,
            title: id,
            description: 'Unable to read pack metadata.',
            color: 0xFF607D8B,
            isInstalled: true,
          ));
        }
      }
    }
    return infos;
  }

  void _refresh() {
    setState(() {
      _installedFuture = _loadInstalled();
      _importError = null;
    });
    widget.onChanged();
  }

  Future<void> _importPack() async {
    setState(() {
      _importing = true;
      _importError = null;
    });

    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['zip'],
        withData: true,
      );
      if (result == null || result.files.isEmpty) {
        setState(() => _importing = false);
        return;
      }

      final bytes = result.files.single.bytes;
      if (bytes == null) {
        setState(() {
          _importing = false;
          _importError = 'Could not read file. Please try again.';
        });
        return;
      }

      await _doImport(bytes);
    } catch (e) {
      if (mounted) {
        setState(() {
          _importing = false;
          _importError = 'Unexpected error: $e';
        });
      }
    }
  }

  Future<void> _doImport(Uint8List bytes, {bool replace = false}) async {
    final importer = PackImporter(widget.registry.storage);
    try {
      final title = await importer.importZip(bytes, replace: replace);
      if (!mounted) return;
      setState(() => _importing = false);
      _refresh();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('"$title" imported successfully.'),
          behavior: SnackBarBehavior.floating,
        ),
      );
    } on PackConflictError catch (e) {
      if (!mounted) return;
      setState(() => _importing = false);
      final confirmed = await _showReplaceDialog(e.existingTitle);
      if (confirmed == true) {
        setState(() => _importing = true);
        await _doImport(bytes, replace: true);
      }
    } on PackImportError catch (e) {
      if (!mounted) return;
      setState(() {
        _importing = false;
        _importError = e.message;
      });
    }
  }

  Future<bool?> _showReplaceDialog(String packTitle) => showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          title: const Text('Replace existing pack?'),
          content: Text(
            '"$packTitle" is already installed. '
            'Do you want to replace it with this version?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Replace'),
            ),
          ],
        ),
      );

  Future<void> _deletePack(PackInfo info) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Delete pack?'),
        content: Text(
          'Remove "${info.title}" from your device? '
          'You can re-import it at any time.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: Colors.red.shade700),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await widget.registry.delete(info.id);
      _refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.55,
      minChildSize: 0.35,
      maxChildSize: 0.9,
      expand: false,
      builder: (_, scrollController) => Column(
        children: [
          // Handle
          const SizedBox(height: 12),
          Center(
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.grey.shade300,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 8),

          // Header
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: Row(
              children: [
                const Text(
                  'Manage Packs',
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                    color: Colors.black87,
                  ),
                ),
                const Spacer(),
                IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ],
            ),
          ),

          const Divider(height: 1),

          Expanded(
            child: ListView(
              controller: scrollController,
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
              children: [
                // Import button
                FilledButton.icon(
                  onPressed: _importing ? null : _importPack,
                  icon: _importing
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white),
                        )
                      : const Icon(Icons.upload_file),
                  label:
                      Text(_importing ? 'Importing…' : 'Import Pack (.zip)'),
                  style: FilledButton.styleFrom(
                    minimumSize: const Size.fromHeight(48),
                    backgroundColor: const Color(0xFF2196F3),
                  ),
                ),

                if (_importError != null) ...[
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.red.shade50,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.red.shade200),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(Icons.error_outline,
                            color: Colors.red.shade700, size: 18),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            _importError!,
                            style: TextStyle(
                                color: Colors.red.shade800, fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],

                const SizedBox(height: 24),

                // Installed packs section
                Text(
                  'Installed packs',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: Colors.grey.shade600,
                    letterSpacing: 0.5,
                  ),
                ),
                const SizedBox(height: 8),

                FutureBuilder<List<PackInfo>>(
                  future: _installedFuture,
                  builder: (context, snap) {
                    if (snap.connectionState == ConnectionState.waiting) {
                      return const Center(
                        child: Padding(
                          padding: EdgeInsets.all(24),
                          child: CircularProgressIndicator(),
                        ),
                      );
                    }
                    final packs = snap.data ?? [];
                    if (packs.isEmpty) {
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 24),
                        child: Column(
                          children: [
                            Icon(Icons.inbox_outlined,
                                size: 48, color: Colors.grey.shade400),
                            const SizedBox(height: 12),
                            Text(
                              'No packs installed yet.',
                              style: TextStyle(color: Colors.grey.shade600),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'Zip your pack folder and tap Import above.',
                              style: TextStyle(
                                  color: Colors.grey.shade500, fontSize: 12),
                              textAlign: TextAlign.center,
                            ),
                          ],
                        ),
                      );
                    }
                    return Column(
                      children: packs
                          .map((info) => _InstalledPackTile(
                                info: info,
                                onDelete: () => _deletePack(info),
                              ))
                          .toList(),
                    );
                  },
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _InstalledPackTile extends StatelessWidget {
  final PackInfo info;
  final VoidCallback onDelete;

  const _InstalledPackTile({required this.info, required this.onDelete});

  @override
  Widget build(BuildContext context) {
    final base = Color(info.color);
    final bg = Color.lerp(base, Colors.white, 0.7)!;

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: base.withOpacity(0.3)),
      ),
      child: ListTile(
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
        leading: info.coverImage != null
            ? ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: Image(
                  image: info.coverImage!,
                  width: 42,
                  height: 42,
                  fit: BoxFit.cover,
                  errorBuilder: (_, __, ___) => Icon(Icons.grid_view,
                      color: base, size: 28),
                ),
              )
            : Icon(Icons.grid_view, color: base, size: 28),
        title: Text(
          info.title,
          style: const TextStyle(
              fontWeight: FontWeight.w600, fontSize: 14),
        ),
        subtitle: info.description.isNotEmpty
            ? Text(
                info.description,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style:
                    TextStyle(fontSize: 12, color: Colors.grey.shade600),
              )
            : null,
        trailing: IconButton(
          icon: Icon(Icons.delete_outline, color: Colors.red.shade400),
          tooltip: 'Delete pack',
          onPressed: onDelete,
        ),
      ),
    );
  }
}
