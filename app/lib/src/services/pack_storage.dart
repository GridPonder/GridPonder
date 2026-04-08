// Selects the right PackStorage implementation at compile time.
// On native platforms (dart:io available): FilesystemPackStorage.
// On web (dart:html): InMemoryPackStorage.
export 'pack_storage_impl.dart'
    if (dart.library.io) 'pack_storage_impl_native.dart';
