from __future__ import annotations

import pytest
from smolagents import LiteLLMModel, ToolCallingAgent

import analytics.llm as llm_module
from analytics.llm import (
    AnalyticsLLMConfigurationError,
    build_analytics_agent_runtime,
    build_litellm_model,
    configure_analytics_llm,
    get_analytics_llm_config,
    get_configured_analytics_llm_config,
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


def test_configured_llm_config_is_loaded_once_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = llm_module._analytics_llm_config
    monkeypatch.setenv("LITELLM_MODEL", "groq/startup-model")
    monkeypatch.setenv("ANALYTICS_SQL_REPAIR_RETRIES", "4")

    try:
        startup_config = configure_analytics_llm()
        monkeypatch.setenv("LITELLM_MODEL", "groq/runtime-change")

        assert startup_config.model_id == "groq/startup-model"
        assert startup_config.sql_repair_retries == 4
        assert get_configured_analytics_llm_config() == startup_config
    finally:
        llm_module._analytics_llm_config = original_config


def test_configured_llm_config_requires_startup_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("analytics.llm._analytics_llm_config", None)

    with pytest.raises(
        AnalyticsLLMConfigurationError,
        match="has not been loaded at app startup",
    ):
        get_configured_analytics_llm_config()


def test_build_analytics_agent_runtime_uses_tool_calling_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LITELLM_MODEL", "groq/llama-3.1-8b-instant")
    monkeypatch.setenv("ANALYTICS_SQL_REPAIR_RETRIES", "2")

    runtime = build_analytics_agent_runtime(config=get_analytics_llm_config())

    assert isinstance(runtime.agent, ToolCallingAgent)
    assert runtime.config.model_id == "groq/llama-3.1-8b-instant"
    assert runtime.agent.model.model_id == "groq/llama-3.1-8b-instant"
    assert "get_schema_context" in runtime.agent.tools
    assert runtime.agent.max_steps == 10
