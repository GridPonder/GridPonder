import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:gridponder_engine/engine.dart';
import '../services/settings_service.dart';

class SettingsScreen extends StatefulWidget {
  final SettingsService settings;
  const SettingsScreen({super.key, required this.settings});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _apiKeyCtrl;
  late final TextEditingController _openAiKeyCtrl;
  late final TextEditingController _googleKeyCtrl;
  late final TextEditingController _ollamaUrlCtrl;
  bool _showKey = false;
  bool _showOpenAiKey = false;
  bool _showGoogleKey = false;

  @override
  void initState() {
    super.initState();
    _apiKeyCtrl =
        TextEditingController(text: widget.settings.apiKey ?? '');
    _openAiKeyCtrl =
        TextEditingController(text: widget.settings.openAiApiKey ?? '');
    _googleKeyCtrl =
        TextEditingController(text: widget.settings.googleApiKey ?? '');
    _ollamaUrlCtrl =
        TextEditingController(text: widget.settings.ollamaBaseUrl);
  }

  @override
  void dispose() {
    _apiKeyCtrl.dispose();
    _openAiKeyCtrl.dispose();
    _googleKeyCtrl.dispose();
    _ollamaUrlCtrl.dispose();
    super.dispose();
  }

  SettingsService get s => widget.settings;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF5F0E8),
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: const Text('Settings',
            style: TextStyle(fontWeight: FontWeight.w600, color: Colors.black87)),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios, color: Colors.black54),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _sectionHeader('Game'),
          _card(
            child: SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Sound'),
              subtitle: const Text('Play sounds during gameplay'),
              value: s.soundEnabled,
              onChanged: (v) async {
                await s.setSoundEnabled(v);
                setState(() {});
              },
            ),
          ),
          const SizedBox(height: 20),
          _sectionHeader('AI Play Mode'),
          if (kIsWeb)
            Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.amber.shade50,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: Colors.amber.shade200),
              ),
              child: Row(
                children: [
                  Icon(Icons.info_outline, size: 18, color: Colors.amber.shade700),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'AI play is not available in the browser. Use the macOS app for AI features.',
                      style: TextStyle(fontSize: 13, color: Colors.amber.shade900),
                    ),
                  ),
                ],
              ),
            ),
          _card(
            child: Column(
              children: [
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Enable AI Play'),
                  subtitle: const Text('Show AI controls on the play screen'),
                  value: s.aiPlayEnabled,
                  onChanged: kIsWeb
                      ? null
                      : (v) async {
                          await s.setAiPlayEnabled(v);
                          setState(() {});
                        },
                ),
              ],
            ),
          ),
          if (s.aiPlayEnabled) ...[
            const SizedBox(height: 20),
            _sectionHeader('Agent Configuration'),
            _card(
              child: Column(
                children: [
                  _dropdownTile(
                    label: 'Agent type',
                    value: s.agentType,
                    items: const {
                      'random': 'Random',
                      'llm': 'Anthropic',
                      'openai': 'OpenAI',
                      'google': 'Google Gemini',
                      'ollama': 'Ollama (local)',
                    },
                    onChanged: (v) async {
                      await s.setAgentType(v!);
                      setState(() {});
                    },
                  ),
                  if (s.agentType == 'ollama') ...[
                    const Divider(height: 1),
                    _dropdownTile(
                      label: 'Model',
                      value: s.ollamaModel,
                      items: {
                        for (final m in OllamaModel.all)
                          m: OllamaModel.displayName(m)
                      },
                      onChanged: (v) async {
                        await s.setOllamaModel(v!);
                        setState(() {});
                      },
                    ),
                    const Divider(height: 1),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Think mode'),
                      subtitle: Text(
                        OllamaModel.supportsThinking(s.ollamaModel)
                            ? 'Show reasoning in step-by-step mode'
                            : 'Not available for ${OllamaModel.displayName(s.ollamaModel)}',
                      ),
                      value: s.ollamaThinkEnabled &&
                          OllamaModel.supportsThinking(s.ollamaModel),
                      onChanged: OllamaModel.supportsThinking(s.ollamaModel)
                          ? (v) async {
                              await s.setOllamaThinkEnabled(v);
                              setState(() {});
                            }
                          : null,
                    ),
                    const Divider(height: 1),
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          TextField(
                            controller: _ollamaUrlCtrl,
                            decoration: InputDecoration(
                              labelText: 'Ollama URL',
                              hintText: 'http://localhost:11434',
                              border: InputBorder.none,
                              suffixIcon: IconButton(
                                icon: const Icon(Icons.save, size: 20),
                                onPressed: () async {
                                  await s.setOllamaBaseUrl(_ollamaUrlCtrl.text);
                                  if (mounted) {
                                    ScaffoldMessenger.of(context).showSnackBar(
                                        const SnackBar(
                                            content: Text('Ollama URL saved'),
                                            duration: Duration(seconds: 1)));
                                  }
                                },
                              ),
                            ),
                          ),
                          Text(
                            'Default: http://localhost:11434',
                            style: TextStyle(
                                fontSize: 11, color: Colors.grey.shade500),
                          ),
                        ],
                      ),
                    ),
                  ],
                  if (s.agentType == 'llm') ...[
                    const Divider(height: 1),
                    _dropdownTile(
                      label: 'Model',
                      value: s.llmModel,
                      items: {
                        for (final m in AnthropicModel.all)
                          m: AnthropicModel.displayName(m)
                      },
                      onChanged: (v) async {
                        await s.setLlmModel(v!);
                        setState(() {});
                      },
                    ),
                    const Divider(height: 1),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Extended thinking'),
                      subtitle: Text(
                        AnthropicModel.supportsThinking(s.llmModel)
                            ? 'Show reasoning in step-by-step mode'
                            : 'Not available for ${AnthropicModel.displayName(s.llmModel)}',
                      ),
                      value: s.thinkingEnabled &&
                          AnthropicModel.supportsThinking(s.llmModel),
                      onChanged: AnthropicModel.supportsThinking(s.llmModel)
                          ? (v) async {
                              await s.setThinkingEnabled(v);
                              setState(() {});
                            }
                          : null,
                    ),
                    const Divider(height: 1),
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          TextField(
                            controller: _apiKeyCtrl,
                            obscureText: !_showKey,
                            decoration: InputDecoration(
                              labelText: 'API Key',
                              hintText: 'sk-ant-...',
                              border: InputBorder.none,
                              suffixIcon: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  IconButton(
                                    icon: Icon(
                                        _showKey
                                            ? Icons.visibility_off
                                            : Icons.visibility,
                                        size: 20),
                                    onPressed: () =>
                                        setState(() => _showKey = !_showKey),
                                  ),
                                  IconButton(
                                    icon: const Icon(Icons.save, size: 20),
                                    onPressed: () async {
                                      await s.setApiKey(_apiKeyCtrl.text);
                                      if (mounted) {
                                        ScaffoldMessenger.of(context)
                                            .showSnackBar(const SnackBar(
                                                content: Text('API key saved'),
                                                duration:
                                                    Duration(seconds: 1)));
                                      }
                                    },
                                  ),
                                ],
                              ),
                            ),
                          ),
                          Text(
                            'Stored locally. Only sent to api.anthropic.com.',
                            style: TextStyle(
                                fontSize: 11, color: Colors.grey.shade500),
                          ),
                        ],
                      ),
                    ),
                  ],
                  if (s.agentType == 'openai') ...[
                    const Divider(height: 1),
                    _dropdownTile(
                      label: 'Model',
                      value: s.openAiModel,
                      items: {
                        for (final m in OpenAIModel.all)
                          m: OpenAIModel.displayName(m)
                      },
                      onChanged: (v) async {
                        await s.setOpenAiModel(v!);
                        setState(() {});
                      },
                    ),
                    const Divider(height: 1),
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          TextField(
                            controller: _openAiKeyCtrl,
                            obscureText: !_showOpenAiKey,
                            decoration: InputDecoration(
                              labelText: 'API Key',
                              hintText: 'sk-...',
                              border: InputBorder.none,
                              suffixIcon: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  IconButton(
                                    icon: Icon(
                                        _showOpenAiKey
                                            ? Icons.visibility_off
                                            : Icons.visibility,
                                        size: 20),
                                    onPressed: () => setState(
                                        () => _showOpenAiKey = !_showOpenAiKey),
                                  ),
                                  IconButton(
                                    icon: const Icon(Icons.save, size: 20),
                                    onPressed: () async {
                                      await s.setOpenAiApiKey(
                                          _openAiKeyCtrl.text);
                                      if (mounted) {
                                        ScaffoldMessenger.of(context)
                                            .showSnackBar(const SnackBar(
                                                content:
                                                    Text('API key saved'),
                                                duration:
                                                    Duration(seconds: 1)));
                                      }
                                    },
                                  ),
                                ],
                              ),
                            ),
                          ),
                          Text(
                            'Stored locally. Only sent to api.openai.com.',
                            style: TextStyle(
                                fontSize: 11, color: Colors.grey.shade500),
                          ),
                        ],
                      ),
                    ),
                  ],
                  if (s.agentType == 'google') ...[
                    const Divider(height: 1),
                    _dropdownTile(
                      label: 'Model',
                      value: s.googleModel,
                      items: {
                        for (final m in GoogleModel.all)
                          m: GoogleModel.displayName(m)
                      },
                      onChanged: (v) async {
                        await s.setGoogleModel(v!);
                        setState(() {});
                      },
                    ),
                    const Divider(height: 1),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Extended thinking'),
                      subtitle: Text(
                        GoogleModel.supportsThinking(s.googleModel)
                            ? 'Show reasoning in step-by-step mode'
                            : 'Not available for ${GoogleModel.displayName(s.googleModel)}',
                      ),
                      value: s.googleThinkingEnabled &&
                          GoogleModel.supportsThinking(s.googleModel),
                      onChanged: GoogleModel.supportsThinking(s.googleModel)
                          ? (v) async {
                              await s.setGoogleThinkingEnabled(v);
                              setState(() {});
                            }
                          : null,
                    ),
                    const Divider(height: 1),
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          TextField(
                            controller: _googleKeyCtrl,
                            obscureText: !_showGoogleKey,
                            decoration: InputDecoration(
                              labelText: 'API Key',
                              hintText: 'AIza...',
                              border: InputBorder.none,
                              suffixIcon: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  IconButton(
                                    icon: Icon(
                                        _showGoogleKey
                                            ? Icons.visibility_off
                                            : Icons.visibility,
                                        size: 20),
                                    onPressed: () => setState(
                                        () => _showGoogleKey = !_showGoogleKey),
                                  ),
                                  IconButton(
                                    icon: const Icon(Icons.save, size: 20),
                                    onPressed: () async {
                                      await s.setGoogleApiKey(
                                          _googleKeyCtrl.text);
                                      if (mounted) {
                                        ScaffoldMessenger.of(context)
                                            .showSnackBar(const SnackBar(
                                                content:
                                                    Text('API key saved'),
                                                duration:
                                                    Duration(seconds: 1)));
                                      }
                                    },
                                  ),
                                ],
                              ),
                            ),
                          ),
                          Text(
                            'Stored locally. Only sent to generativelanguage.googleapis.com.',
                            style: TextStyle(
                                fontSize: 11, color: Colors.grey.shade500),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 20),
            _sectionHeader('Playback'),
            _card(
              child: Column(
                children: [
                  _dropdownTile(
                    label: 'Mode',
                    value: s.playbackMode,
                    items: const {
                      'continuous': 'Continuous',
                      'step': 'Step-by-step',
                    },
                    onChanged: (v) async {
                      await s.setPlaybackMode(v!);
                      setState(() {});
                    },
                  ),
                  if (s.playbackMode == 'continuous') ...[
                    const Divider(height: 1),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text('Delay: ${s.stepDelayMs} ms'),
                      subtitle: Slider(
                        value: s.stepDelayMs.toDouble(),
                        min: 100,
                        max: 2000,
                        divisions: 19,
                        onChanged: (v) async {
                          await s.setStepDelayMs(v.round());
                          setState(() {});
                        },
                      ),
                    ),
                  ],
                  const Divider(height: 1),
                  _dropdownTile(
                    label: 'Inference mode',
                    value: s.inferenceMode,
                    items: const {
                      'single': 'Single (1 action/call)',
                      'fixed-n': 'Fixed-N (batch)',
                      'flex-n': 'Flex-N (model chooses)',
                      'full': 'Full (one-shot)',
                    },
                    onChanged: (v) async {
                      await s.setInferenceMode(v!);
                      setState(() {});
                    },
                  ),
                  if (s.inferenceMode == 'fixed-n') ...[
                    const Divider(height: 1),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text('Batch size: ${s.stepSizeN} actions/call'),
                      subtitle: Slider(
                        value: s.stepSizeN.toDouble(),
                        min: 2,
                        max: 10,
                        divisions: 8,
                        onChanged: (v) async {
                          await s.setStepSizeN(v.round());
                          setState(() {});
                        },
                      ),
                    ),
                  ],
                  if (s.inferenceMode == 'flex-n') ...[
                    const Divider(height: 1),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        s.maxN == 0
                            ? 'Max actions/call: unlimited'
                            : 'Max actions/call: ${s.maxN}',
                      ),
                      subtitle: Slider(
                        value: s.maxN.toDouble(),
                        min: 0,
                        max: 10,
                        divisions: 10,
                        label: s.maxN == 0 ? '∞' : '${s.maxN}',
                        onChanged: (v) async {
                          await s.setMaxN(v.round());
                          setState(() {});
                        },
                      ),
                    ),
                  ],
                  const Divider(height: 1),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Anonymous mode'),
                    subtitle: const Text(
                        'Hide entity names and action semantics (ARC-AGI style)'),
                    value: s.anonymize,
                    onChanged: (v) async {
                      await s.setAnonymize(v);
                      setState(() {});
                    },
                  ),
                  const Divider(height: 1),
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(
                        'Auto-reset: ${s.autoResetMultiplier}× gold-path length'),
                    subtitle: Slider(
                      value: s.autoResetMultiplier.toDouble(),
                      min: 1,
                      max: 10,
                      divisions: 9,
                      onChanged: (v) async {
                        await s.setAutoResetMultiplier(v.round());
                        setState(() {});
                      },
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _sectionHeader(String text) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(text,
            style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: Colors.grey.shade600,
                letterSpacing: 0.5)),
      );

  Widget _card({required Widget child}) => Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: child,
      );

  Widget _dropdownTile({
    required String label,
    required String value,
    required Map<String, String> items,
    required void Function(String?) onChanged,
  }) {
    return Row(
      children: [
        Text(label, style: const TextStyle(fontSize: 15)),
        const Spacer(),
        DropdownButton<String>(
          value: value,
          underline: const SizedBox.shrink(),
          items: items.entries
              .map((e) => DropdownMenuItem(value: e.key, child: Text(e.value)))
              .toList(),
          onChanged: onChanged,
        ),
      ],
    );
  }
}
