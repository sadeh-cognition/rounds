from __future__ import annotations

from analytics.agent_tools import SQLExecutionRecord
from analytics.agentic_qa import (
    AGENT_INSTRUCTIONS,
    AgentFinalAnswer,
    _build_chat_response,
)


def test_agent_instructions_require_clarification_for_missing_details() -> None:
    assert "unstated detail" in AGENT_INSTRUCTIONS
    assert "needs_clarification=true" in AGENT_INSTRUCTIONS


def test_agent_clarification_response_does_not_include_rows() -> None:
    response = _build_chat_response(
        final_answer=AgentFinalAnswer(
            message_text="Which revenue definition should I use?",
            needs_clarification=True,
            clarification_question="Which revenue definition should I use?",
        ),
        executions=[
            SQLExecutionRecord(
                sql="SELECT country FROM daily_metrics",
                validation_status="executed",
                error="",
                columns=["country"],
                rows=[{"country": "US"}],
                row_count=1,
                returned_row_count=1,
                truncated=False,
            )
        ],
        sql_visibility_preference="requested",
    )

    assert response.table_rows == []
    assert response.sql_snippet is None
    assert response.clarification is not None
    assert response.clarification.required is True
    assert response.clarification.question == "Which revenue definition should I use?"
    assert response.clarification.context == {"source": "analytics_agent"}


def test_agent_answer_does_not_add_notes() -> None:
    response = _build_chat_response(
        final_answer=AgentFinalAnswer(message_text="There are 2 apps."),
        executions=[],
        sql_visibility_preference="auto",
    )

    assert response.message_text == "There are 2 apps."
    assert response.clarification is None
