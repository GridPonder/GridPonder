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

  // Anthropic
  String get llmModel =>
      _prefs.getString('llm_model') ?? 'claude-haiku-4-5-20251001';
  Future<void> setLlmModel(String v) => _prefs.setString('llm_model', v);

  bool get thinkingEnabled => _prefs.getBool('thinking_enabled') ?? false;
  Future<void> setThinkingEnabled(bool v) =>
      _prefs.setBool('thinking_enabled', v);

  // OpenAI
  String? get openAiApiKey => _prefs.getString('openai_api_key');
  Future<void> setOpenAiApiKey(String key) =>
      _prefs.setString('openai_api_key', key.trim());

  String get openAiModel =>
      _prefs.getString('openai_model') ?? 'gpt-4o-mini';
  Future<void> setOpenAiModel(String v) =>
      _prefs.setString('openai_model', v);

  // Google
  String? get googleApiKey => _prefs.getString('google_api_key');
  Future<void> setGoogleApiKey(String key) =>
      _prefs.setString('google_api_key', key.trim());

  String get googleModel =>
      _prefs.getString('google_model') ?? 'gemini-2.0-flash';
  Future<void> setGoogleModel(String v) =>
      _prefs.setString('google_model', v);

  bool get googleThinkingEnabled =>
      _prefs.getBool('google_thinking_enabled') ?? false;
  Future<void> setGoogleThinkingEnabled(bool v) =>
      _prefs.setBool('google_thinking_enabled', v);

  // Ollama
  String get ollamaBaseUrl =>
      _prefs.getString('ollama_base_url') ?? 'http://localhost:11434';
  Future<void> setOllamaBaseUrl(String v) =>
      _prefs.setString('ollama_base_url', v.trim());

  String get ollamaModel =>
      _prefs.getString('ollama_model') ?? 'qwen3.5:4b';
  Future<void> setOllamaModel(String v) =>
      _prefs.setString('ollama_model', v);

  bool get ollamaThinkEnabled =>
      _prefs.getBool('ollama_think_enabled') ?? false;
  Future<void> setOllamaThinkEnabled(bool v) =>
      _prefs.setBool('ollama_think_enabled', v);

  // --- Inference mode ---
  /// 'single' | 'fixed-n' | 'flex-n' | 'full'
  String get inferenceMode => _prefs.getString('inference_mode') ?? 'single';
  Future<void> setInferenceMode(String v) =>
      _prefs.setString('inference_mode', v);

  /// Max actions per LLM call for fixed-n mode.
  int get stepSizeN => _prefs.getInt('step_size_n') ?? 3;
  Future<void> setStepSizeN(int v) => _prefs.setInt('step_size_n', v);

  /// Max actions per LLM call for flex-n mode (0 = unlimited).
  int get maxN => _prefs.getInt('max_n') ?? 0;
  Future<void> setMaxN(int v) => _prefs.setInt('max_n', v);

  // --- Anonymous mode ---
  /// When true, entity kinds and action IDs are anonymised in the prompt.
  bool get anonymize => _prefs.getBool('anonymize') ?? false;
  Future<void> setAnonymize(bool v) => _prefs.setBool('anonymize', v);

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
