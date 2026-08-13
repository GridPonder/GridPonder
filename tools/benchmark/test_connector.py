from __future__ import annotations

import os
from pathlib import Path

from agent_client import _load_connector, call_llm
from connector_api import estimate_cost


def test_local_connector_contract() -> None:
    fixture_dir = Path(__file__).parent / "_fixtures" / "connectors"
    previous = os.environ.get("GRIDPONDER_CONNECTOR_DIR")
    os.environ["GRIDPONDER_CONNECTOR_DIR"] = str(fixture_dir)
    _load_connector.cache_clear()
    try:
        result = call_llm(
            "prompt",
            "fake-model",
            connector="fake",
            max_tokens=50,
        )
    finally:
        _load_connector.cache_clear()
        if previous is None:
            os.environ.pop("GRIDPONDER_CONNECTOR_DIR", None)
        else:
            os.environ["GRIDPONDER_CONNECTOR_DIR"] = previous

    assert result[0] == '{"action":"move","direction":"right"}'
    assert result[2:] == (10, 20, 5, 0.25, "summary")


def test_configured_cost_estimate() -> None:
    assert estimate_cost(
        1_000_000,
        500_000,
        {
            "input_per_million": 2.0,
            "output_per_million": 8.0,
        },
    ) == 6.0
    assert estimate_cost(100, 100, None) is None


if __name__ == "__main__":
    test_local_connector_contract()
    test_configured_cost_estimate()
    print("2 passed")
