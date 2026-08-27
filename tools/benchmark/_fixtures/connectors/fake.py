from connector_api import CompletionResult


class _FakeConnector:
    def complete(self, request):
        return CompletionResult(
            text='{"action":"move","direction":"right"}',
            input_tokens=10,
            reasoning_tokens=20,
            output_tokens=5,
            cost_usd=0.25,
            reasoning="summary",
        )


connector = _FakeConnector()
