from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Any

from loguru import logger
import sqlglot
import sqlglot.errors
from django.conf import settings
from django.db import connection
from smolagents import tool
from sqlglot import exp

from analytics.schema import ALLOWED_TABLE_NAMES, get_analytics_schema_context


@dataclass(frozen=True)
class SQLExecutionRecord:
    sql: str
    validation_status: str
    error: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    returned_row_count: int
    truncated: bool


_sql_execution_records: ContextVar[list[SQLExecutionRecord]] = ContextVar(
    "sql_execution_records",
    default=[],
)


def reset_sql_execution_records() -> None:
    _sql_execution_records.set([])


def get_sql_execution_records() -> list[SQLExecutionRecord]:
    return list(_sql_execution_records.get())


@tool
def get_schema_context(conversation_context_json: str = "{}") -> dict[str, Any]:
    """Return allowed analytics schema and SQL rules for portfolio questions.

    Args:
        conversation_context_json: Optional JSON object string containing persisted
            Slack thread context and prior-turn details for follow-up questions.
    """
    try:
        conversation_context = json.loads(conversation_context_json)
    except json.JSONDecodeError:
        conversation_context = {}
    if not isinstance(conversation_context, dict):
        conversation_context = {}
    return get_analytics_schema_context(conversation_context=conversation_context)


@tool
def get_today_date() -> str:
    """Return today's UTC calendar date in ISO-8601 YYYY-MM-DD format."""
    return datetime.now(timezone.utc).date().isoformat()


@tool
def run_readonly_sql(sql: str) -> dict[str, Any]:
    """Validate and execute one read-only PostgreSQL query against analytics data.

    Args:
        sql: A single SELECT or WITH query using only the apps and daily_metrics
            tables. Do not include multiple statements, writes, or references to
            Django/internal tables. If this tool returns an error, use the error
            text to repair the SQL and call the tool again.
    """
    try:
        normalized_sql = _validate_readonly_sql(sql)
        result = _execute_readonly_sql(normalized_sql)
    except Exception as exc:
        error = str(exc)
        _record_sql_execution(
            SQLExecutionRecord(
                sql=sql,
                validation_status="error",
                error=error,
                columns=[],
                rows=[],
                row_count=0,
                returned_row_count=0,
                truncated=False,
            )
        )
        return {
            "ok": False,
            "sql": sql,
            "error": error,
            "hint": "Repair the SQL using this error and call run_readonly_sql again.",
        }

    logger.info(f"SQL run {result['row_count']}")
    _record_sql_execution(
        SQLExecutionRecord(
            sql=normalized_sql,
            validation_status="executed",
            error="",
            columns=result["columns"],
            rows=result["rows"],
            row_count=result["row_count"],
            returned_row_count=result["returned_row_count"],
            truncated=result["truncated"],
        )
    )
    return {
        "ok": True,
        "sql": normalized_sql,
        **result,
    }


def _record_sql_execution(record: SQLExecutionRecord) -> None:
    records = list(_sql_execution_records.get())
    records.append(record)
    _sql_execution_records.set(records)


def _validate_readonly_sql(sql: str) -> str:
    normalized_sql = sql.strip().rstrip(";")
    if not normalized_sql:
        raise ValueError("SQL must not be empty.")

    try:
        statements = sqlglot.parse(normalized_sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"SQL parse failed: {exc}") from exc

    if len(statements) != 1:
        raise ValueError("SQL must contain exactly one statement.")

    expression = statements[0]
    if not isinstance(expression, exp.Query):
        raise ValueError("Only SELECT or WITH read-only queries are allowed.")

    cte_names = {
        cte.alias_or_name.lower()
        for cte in expression.find_all(exp.CTE)
        if cte.alias_or_name
    }
    referenced_tables = {
        table.name.lower()
        for table in expression.find_all(exp.Table)
        if table.name and table.name.lower() not in cte_names
    }
    allowed_tables = {table_name.lower() for table_name in ALLOWED_TABLE_NAMES}
    forbidden_tables = referenced_tables - allowed_tables
    if forbidden_tables:
        raise ValueError(
            "SQL references forbidden table(s): "
            + ", ".join(sorted(forbidden_tables))
            + ". Allowed tables are: "
            + ", ".join(sorted(allowed_tables))
            + "."
        )

    if not referenced_tables:
        raise ValueError("SQL must read from at least one allowed analytics table.")

    return normalized_sql


def _execute_readonly_sql(sql: str) -> dict[str, Any]:
    max_rows = settings.ANALYTICS_MAX_ROW_LIMIT
    count_sql = f"SELECT COUNT(*) FROM ({sql}) AS analytics_query_count"
    limited_sql = f"SELECT * FROM ({sql}) AS analytics_query LIMIT %s"

    with connection.cursor() as cursor:
        cursor.execute(count_sql)
        count_row = cursor.fetchone()
        assert count_row is not None, "COUNT(*) query returned no rows"
        row_count = int(count_row[0])

        cursor.execute(limited_sql, [max_rows])
        columns = [column[0] for column in cursor.description or []]
        raw_rows = cursor.fetchall()

    rows = [
        {
            column: _to_jsonable_value(value)
            for column, value in zip(columns, raw_row, strict=True)
        }
        for raw_row in raw_rows
    ]
    returned_row_count = len(rows)
    return {
        "columns": columns,
        "rows": rows,
        "row_count": row_count,
        "returned_row_count": returned_row_count,
        "truncated": row_count > returned_row_count,
    }


def _to_jsonable_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
