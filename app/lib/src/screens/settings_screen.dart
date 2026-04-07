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
  bool _showKey = false;

  @override
  void initState() {
    super.initState();
    _apiKeyCtrl =
        TextEditingController(text: widget.settings.apiKey ?? '');
  }

  @override
  void dispose() {
    _apiKeyCtrl.dispose();
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
          _card(
            child: Column(
              children: [
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Enable AI Play'),
                  subtitle: const Text('Show AI controls on the play screen'),
                  value: s.aiPlayEnabled,
                  onChanged: (v) async {
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
                    items: const {'random': 'Random', 'llm': 'LLM (Anthropic)'},
                    onChanged: (v) async {
                      await s.setAgentType(v!);
                      setState(() {});
                    },
                  ),
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
