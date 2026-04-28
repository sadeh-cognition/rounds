from __future__ import annotations

import pytest
from smolagents import LiteLLMModel, ToolCallingAgent

from analytics.llm import (
    AnalyticsLLMConfigurationError,
    build_analytics_agent_runtime,
    build_litellm_model,
    get_analytics_llm_config,
)


def test_llm_config_requires_model_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITELLM_MODEL", raising=False)

    with pytest.raises(
        AnalyticsLLMConfigurationError,
        match="LITELLM_MODEL must be configured",
    ):
        get_analytics_llm_config()


def test_llm_config_uses_configured_litellm_model_without_default_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LITELLM_MODEL", " groq/llama-3.1-8b-instant ")
    monkeypatch.setenv("ANALYTICS_SQL_REPAIR_RETRIES", "3")

    config = get_analytics_llm_config()
    model = build_litellm_model(config)

    assert config.model_id == "groq/llama-3.1-8b-instant"
    assert config.sql_repair_retries == 3
    assert isinstance(model, LiteLLMModel)
    assert model.model_id == "groq/llama-3.1-8b-instant"


@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_llm_config_rejects_invalid_sql_repair_retries(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("LITELLM_MODEL", "groq/llama-3.1-8b-instant")
    monkeypatch.setenv("ANALYTICS_SQL_REPAIR_RETRIES", value)

    with pytest.raises(
        AnalyticsLLMConfigurationError,
        match="ANALYTICS_SQL_REPAIR_RETRIES must be a positive integer",
    ):
        get_analytics_llm_config()


def test_build_analytics_agent_runtime_uses_tool_calling_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LITELLM_MODEL", "groq/llama-3.1-8b-instant")
    monkeypatch.setenv("ANALYTICS_SQL_REPAIR_RETRIES", "2")

    runtime = build_analytics_agent_runtime()

    assert isinstance(runtime.agent, ToolCallingAgent)
    assert runtime.config.model_id == "groq/llama-3.1-8b-instant"
    assert runtime.agent.model.model_id == "groq/llama-3.1-8b-instant"
    assert "get_schema_context" in runtime.agent.tools
    assert runtime.agent.max_steps == 3
