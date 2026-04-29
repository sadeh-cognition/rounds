import json
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from loguru import logger
from pydantic import BaseModel, ValidationError

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
from analytics.llm import (
    AnalyticsLLMConfig,
    ResultPresentationFormat,
    build_analytics_agent_runtime,
)
from analytics.tracing import configure_phoenix_tracing


class AgentFinalAnswer(BaseModel):
    message_text: str
    result_presentation: ResultPresentationFormat = "detailed_table"
    needs_clarification: bool = False
    clarification_question: str = ""


@dataclass(frozen=True)
class AgenticQAResult:
    response: AnalyticsChatResponse
    executions: list[SQLExecutionRecord]
    raw_agent_answer: str


AGENT_INSTRUCTIONS = """
You answer Slack portfolio analytics questions by generating and executing SQL.
Provide responses either in plain text or as detailed tables, depending on query complexity.
After a successful run_readonly_sql call, call decide_result_presentation with the user question, result columns, result rows, and row count.
Use the tool decision as result_presentation in the final answer.
Use result_presentation=plain_text for scalar, single-row, or short results that are easier to read in prose.
Use result_presentation=detailed_table for multi-row, grouped, ranked, comparative, or wide results where rows and columns matter.
Table responses include clear descriptions and note any assumptions made.
If the request is missing a necessary business definition, entity, date range, grouping, comparison target, or other unstated detail, ask concise clarification questions instead of running SQL.
Do not make assumptions or decisions for what a reasonable or default value should be. Instead ask for clarifications.
If there are any ambiguities in the question, ask concise clarification questions to resolve them. Do not try to resolve such issues.
Use only the given database schema, metric definitions, row limits, and conversation context.
If there are no clarifications needed generate one read-only PostgreSQL SELECT/WITH query and call run_readonly_sql.
If run_readonly_sql returns ok=false, repair the SQL using the returned error and call run_readonly_sql again. Do not give up until the configured step limit is reached.
Use only the rows returned by run_readonly_sql to answer. Do not invent data and do not run hidden availability checks after a no-data result.
If user provides a clarification and there are not more ambiguities or missing details, proceed with generating SQL and answering.
If a date range is needed and not given by the user ask for clarification.
Do not make assumptions about what a reasonable default date range would be. Always ask for clarification if a date range is needed and not provided.
Return the final answer as JSON with exactly these keys:
message_text, result_presentation, needs_clarification, clarification_question.
When asking for clarification, set needs_clarification=true.
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
                "needs_clarification": False,
                "clarification_question": "",
            },
        },
        default=str,
    )
    raw_answer = runtime.agent.run(task)
    executions = get_sql_execution_records()
    logger.info(f"SQL Executions: {executions}")
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
    if final_answer.needs_clarification:
        question = _build_clarification_question(final_answer)
        return AnalyticsChatResponse(
            message_text=question,
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
            sql_snippet=sql_snippet,
        )

    if final_answer.result_presentation == "plain_text":
        return AnalyticsChatResponse(
            message_text=final_answer.message_text,
            sql_snippet=sql_snippet,
            row_count=successful_execution.row_count,
            returned_row_count=successful_execution.returned_row_count,
            truncated=successful_execution.truncated,
        )

    return AnalyticsChatResponse(
        message_text=final_answer.message_text,
        table_columns=successful_execution.columns,
        table_rows=successful_execution.rows[: settings.ANALYTICS_INLINE_ROW_LIMIT],
        sql_snippet=sql_snippet,
        row_count=successful_execution.row_count,
        returned_row_count=successful_execution.returned_row_count,
        truncated=successful_execution.truncated,
    )


def _build_clarification_question(final_answer: AgentFinalAnswer) -> str:
    if final_answer.clarification_question:
        return final_answer.clarification_question
    if final_answer.message_text:
        return final_answer.message_text
    return "Can you clarify the missing detail before I answer?"


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
