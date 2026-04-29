from __future__ import annotations

import io
from types import SimpleNamespace

from loguru import logger as loguru_logger
import pytest
from smolagents import LiteLLMModel, ToolCallingAgent

import analytics.llm as llm_module
from analytics.llm import (
    AnalyticsLLMConfigurationError,
    build_analytics_agent_runtime,
    build_litellm_model,
    configure_analytics_llm,
    decide_result_presentation,
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


def test_configure_analytics_llm_logs_startup_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_config = llm_module._analytics_llm_config
    stream = io.StringIO()
    monkeypatch.setenv("LITELLM_MODEL", "groq/startup-model")
    monkeypatch.setenv("ANALYTICS_SQL_REPAIR_RETRIES", "4")

    sink_id = loguru_logger.add(stream, level="INFO", format="{message}")
    try:
        configure_analytics_llm()

        assert (
            "Analytics LLM config loaded model_id=groq/startup-model, "
            "sql_repair_retries=4"
        ) in stream.getvalue()
    finally:
        loguru_logger.remove(sink_id)
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
    assert "decide_result_presentation" in runtime.agent.tools
    assert runtime.agent.max_steps == 10


def test_decide_result_presentation_uses_configured_litellm_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeModel:
        def generate(self, messages, response_format=None):
            calls.append(
                {
                    "messages": messages,
                    "response_format": response_format,
                }
            )
            return SimpleNamespace(
                content=(
                    '{"presentation_format": "plain_text", '
                    '"rationale": "Single scalar result."}'
                )
            )

    monkeypatch.setattr(llm_module, "build_litellm_model", lambda: FakeModel())

    decision = decide_result_presentation.forward(
        question="How many apps are there?",
        columns_json='["app_count"]',
        rows_json='[{"app_count": 2}]',
        row_count=1,
    )

    assert isinstance(calls, list)
    assert isinstance(calls[0], dict)
    assert isinstance(calls[0]["messages"], list)
    assert isinstance(calls[0]["messages"][1], dict)
    assert decision == {
        "presentation_format": "plain_text",
        "rationale": "Single scalar result.",
    }
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert (
        '"question": "How many apps are there?"' in calls[0]["messages"][1]["content"]
    )
