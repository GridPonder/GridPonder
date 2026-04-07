import 'package:shared_preferences/shared_preferences.dart';

/// Stores user preferences including the Anthropic API key.
/// Backed by SharedPreferences; key is never logged or exposed.
class SettingsService {
  final SharedPreferences _prefs;

  SettingsService._(this._prefs);

  static Future<SettingsService> create() async {
    final prefs = await SharedPreferences.getInstance();
    return SettingsService._(prefs);
  }

  // --- Sound ---
  bool get soundEnabled => _prefs.getBool('sound_enabled') ?? true;
  Future<void> setSoundEnabled(bool v) => _prefs.setBool('sound_enabled', v);

  // --- API key ---
  String? get apiKey => _prefs.getString('anthropic_api_key');
  Future<void> setApiKey(String key) =>
      _prefs.setString('anthropic_api_key', key.trim());
  Future<void> clearApiKey() => _prefs.remove('anthropic_api_key');

  // --- AI play mode ---
  bool get aiPlayEnabled => _prefs.getBool('ai_play_enabled') ?? false;
  Future<void> setAiPlayEnabled(bool v) =>
      _prefs.setBool('ai_play_enabled', v);

  // --- Agent preferences ---
  String get agentType => _prefs.getString('agent_type') ?? 'random';
  Future<void> setAgentType(String v) => _prefs.setString('agent_type', v);

  String get llmModel =>
      _prefs.getString('llm_model') ?? 'claude-haiku-4-5-20251001';
  Future<void> setLlmModel(String v) => _prefs.setString('llm_model', v);

  bool get thinkingEnabled => _prefs.getBool('thinking_enabled') ?? false;
  Future<void> setThinkingEnabled(bool v) =>
      _prefs.setBool('thinking_enabled', v);

  // --- Playback mode ---
  /// 'continuous' or 'step'
  String get playbackMode => _prefs.getString('playback_mode') ?? 'continuous';
  Future<void> setPlaybackMode(String v) =>
      _prefs.setString('playback_mode', v);

  int get stepDelayMs => _prefs.getInt('step_delay_ms') ?? 600;
  Future<void> setStepDelayMs(int v) => _prefs.setInt('step_delay_ms', v);

  /// Multiplier applied to the gold-path length to compute the per-attempt
  /// action limit before an automatic reset. Default: 3.
  int get autoResetMultiplier => _prefs.getInt('auto_reset_multiplier') ?? 3;
  Future<void> setAutoResetMultiplier(int v) =>
      _prefs.setInt('auto_reset_multiplier', v);
}
