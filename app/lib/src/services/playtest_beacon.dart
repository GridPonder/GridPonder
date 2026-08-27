// Selects the beacon implementation at compile time.
// On web: a real navigator.sendBeacon call.
// On native (dart:io available): a no-op — tracking is only ever built for web.
export 'playtest_beacon_web.dart'
    if (dart.library.io) 'playtest_beacon_stub.dart';
