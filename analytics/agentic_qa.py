from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from analytics.agent_tools import (
    SQLExecutionRecord,
    get_sql_execution_records,
    reset_sql_execution_records,
)
from analytics.chat_schemas import (
    AnalyticsChatResponse,
    AnalyticsClarificationPayload,
    AnalyticsSnippetPayload,
    SqlVisibilityPreference,
)
from analytics.llm import AnalyticsLLMConfig, build_analytics_agent_runtime
from analytics.tracing import configure_phoenix_tracing


class AgentFinalAnswer(BaseModel):
    message_text: str
    assumptions: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str = ""


@dataclass(frozen=True)
class AgenticQAResult:
    response: AnalyticsChatResponse
    executions: list[SQLExecutionRecord]
    raw_agent_answer: str


AGENT_INSTRUCTIONS = """
You answer Slack portfolio analytics questions by generating and executing SQL.

Follow this workflow:
1. Call get_schema_context first and use only the returned schema, metric definitions,
   row limits, and conversation context.
2. Call get_today_date when the question uses relative dates such as today,
   yesterday, this week, this month, or last month.
3. If the request is missing a necessary business definition, entity, date range,
   grouping, or comparison target, ask one concise clarification question instead
   of running SQL.
4. Otherwise generate one read-only PostgreSQL SELECT/WITH query and call
   run_readonly_sql.
5. If run_readonly_sql returns ok=false, repair the SQL using the returned error
   and call run_readonly_sql again. Do not give up until the configured step limit
   is reached.
6. Use only the rows returned by run_readonly_sql to answer. Do not invent data
   and do not run hidden availability checks after a no-data result.

Return the final answer as JSON with exactly these keys:
message_text, assumptions, needs_clarification, clarification_question.
"""


def answer_question_with_agent(
    *,
    question: str,
    conversation_context: dict[str, Any],
    sql_visibility_preference: SqlVisibilityPreference,
    config: AnalyticsLLMConfig,
) -> AgenticQAResult:
    configure_phoenix_tracing()
    reset_sql_execution_records()
    runtime = build_analytics_agent_runtime(
        config=config,
        instructions=AGENT_INSTRUCTIONS,
    )

    task = json.dumps(
        {
            "question": question,
            "conversation_context": conversation_context,
            "sql_visibility_preference": sql_visibility_preference,
            "required_final_answer_format": {
                "message_text": "Natural-language answer for the user.",
                "assumptions": ["Short assumption strings."],
                "needs_clarification": False,
                "clarification_question": "",
            },
        },
        default=str,
    )
    raw_answer = runtime.agent.run(task)
    executions = get_sql_execution_records()
    final_answer = _parse_final_answer(raw_answer)
    response = _build_chat_response(
        final_answer=final_answer,
        executions=executions,
        sql_visibility_preference=sql_visibility_preference,
    )
    return AgenticQAResult(
        response=response,
        executions=executions,
        raw_agent_answer=str(raw_answer),
    )


def _parse_final_answer(raw_answer: Any) -> AgentFinalAnswer:
    if isinstance(raw_answer, AgentFinalAnswer):
        return raw_answer
    if isinstance(raw_answer, dict):
        return AgentFinalAnswer.model_validate(raw_answer)

    answer_text = str(raw_answer).strip()
    try:
        parsed_json = json.loads(answer_text)
    except json.JSONDecodeError:
        return AgentFinalAnswer(message_text=answer_text)

    try:
        return AgentFinalAnswer.model_validate(parsed_json)
    except ValidationError:
        return AgentFinalAnswer(message_text=answer_text)


def _build_chat_response(
    *,
    final_answer: AgentFinalAnswer,
    executions: list[SQLExecutionRecord],
    sql_visibility_preference: SqlVisibilityPreference,
) -> AnalyticsChatResponse:
    assumptions = ["Dates are interpreted as UTC calendar dates."]
    assumptions.extend(
        assumption
        for assumption in final_answer.assumptions
        if assumption and assumption not in assumptions
    )
    if (
        sql_visibility_preference == "requested"
        and "SQL was requested" not in assumptions
    ):
        assumptions.append("SQL was requested")

    if final_answer.needs_clarification:
        question = final_answer.clarification_question or final_answer.message_text
        return AnalyticsChatResponse(
            message_text=question,
            assumptions=assumptions,
            clarification=AnalyticsClarificationPayload(
                required=True,
                question=question,
                context={"source": "analytics_agent"},
            ),
        )

    successful_execution = _last_successful_execution(executions)
    sql_snippet = _build_sql_snippet(
        executions=executions,
        sql_visibility_preference=sql_visibility_preference,
    )
    if successful_execution is None:
        return AnalyticsChatResponse(
            message_text=final_answer.message_text,
            assumptions=assumptions,
            sql_snippet=sql_snippet,
        )

    return AnalyticsChatResponse(
        message_text=final_answer.message_text,
        table_columns=successful_execution.columns,
        table_rows=successful_execution.rows[:25],
        sql_snippet=sql_snippet,
        assumptions=assumptions,
        row_count=successful_execution.row_count,
        returned_row_count=successful_execution.returned_row_count,
        truncated=successful_execution.truncated,
    )


def _last_successful_execution(
    executions: list[SQLExecutionRecord],
) -> SQLExecutionRecord | None:
    for execution in reversed(executions):
        if execution.validation_status == "executed":
            return execution
    return None


def _build_sql_snippet(
    *,
    executions: list[SQLExecutionRecord],
    sql_visibility_preference: SqlVisibilityPreference,
) -> AnalyticsSnippetPayload | None:
    if sql_visibility_preference == "never" or not executions:
        return None
    failed = any(execution.validation_status == "error" for execution in executions)
    if sql_visibility_preference != "requested" and not failed:
        return None

    last_sql = executions[-1].sql
    return AnalyticsSnippetPayload(
        filename="query.sql",
        content=last_sql,
        title="Generated SQL",
        mime_type="application/sql",
    )
