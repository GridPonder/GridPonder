import 'package:web/web.dart' as web;

Future<void> sendBeacon(Uri uri) async {
  web.window.navigator.sendBeacon(uri.toString());
}
