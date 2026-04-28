from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

import djclick as click
from rich.console import Console
from rich.table import Table

from analytics.chat_schemas import (
    AnalyticsChatRequest,
    AnalyticsChatResponse,
    SqlVisibilityPreference,
)
from analytics.chat_service import handle_analytics_chat


DEFAULT_TEAM_ID = "CLI"
DEFAULT_CHANNEL_ID = "CLI"
DEFAULT_THREAD_ID = "cli"
DEFAULT_USER_ID = "cli-user"


def build_cli_chat_request(
    *,
    text: str,
    team_id: str = DEFAULT_TEAM_ID,
    channel_id: str = DEFAULT_CHANNEL_ID,
    thread_id: str = DEFAULT_THREAD_ID,
    user_id: str = DEFAULT_USER_ID,
    sql_visibility_preference: SqlVisibilityPreference = "auto",
    utc_timestamp: datetime | None = None,
) -> AnalyticsChatRequest:
    return AnalyticsChatRequest(
        slack_team_id=team_id,
        slack_channel_id=channel_id,
        slack_thread_id=thread_id,
        slack_user_id=user_id,
        text=text.strip(),
        utc_timestamp=utc_timestamp or datetime.now(timezone.utc),
        sql_visibility_preference=sql_visibility_preference,
    )


def render_cli_response(response: AnalyticsChatResponse, *, console: Console) -> None:
    console.print(response.message_text)

    if response.table_columns and response.table_rows:
        table = Table(show_header=True, header_style="bold")
        for column in response.table_columns:
            table.add_column(column)
        for row in response.table_rows:
            table.add_row(*[_cell_text(row.get(column)) for column in response.table_columns])
        console.print(table)

    if response.truncated:
        console.print(
            f"Showing {response.returned_row_count} of {response.row_count} returned rows."
        )

    if response.clarification is not None and response.clarification.required:
        console.print()
        console.print(f"[bold]Clarification needed:[/bold] {response.clarification.question}")

    for label, snippet in (
        ("CSV", response.csv_snippet),
        ("SQL", response.sql_snippet),
    ):
        if snippet is not None:
            console.print()
            console.print(f"[bold]{label} snippet: {snippet.filename}[/bold]")
            console.print(snippet.content)


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _parse_sql_visibility_preference(
    show_sql: bool,
    hide_sql: bool,
) -> SqlVisibilityPreference:
    if show_sql and hide_sql:
        raise click.ClickException("--show-sql and --hide-sql cannot be used together.")
    if show_sql:
        return "requested"
    if hide_sql:
        return "never"
    return "auto"


@click.command()
@click.argument("text", nargs=-1, required=True)
@click.option("--team-id", default=DEFAULT_TEAM_ID, show_default=True)
@click.option("--channel-id", default=DEFAULT_CHANNEL_ID, show_default=True)
@click.option("--thread-id", default=DEFAULT_THREAD_ID, show_default=True)
@click.option("--user-id", default=DEFAULT_USER_ID, show_default=True)
@click.option("--show-sql", is_flag=True, help="Request SQL output when available.")
@click.option("--hide-sql", is_flag=True, help="Never show SQL output.")
@click.option("--json-output", is_flag=True, help="Print the raw response as JSON.")
def command(
    *,
    text: tuple[str, ...],
    team_id: str,
    channel_id: str,
    thread_id: str,
    user_id: str,
    show_sql: bool,
    hide_sql: bool,
    json_output: bool,
) -> None:
    """Ask the analytics chat backend from a local CLI."""
    question = " ".join(text).strip()
    if not question:
        raise click.ClickException("Question text is required.")

    payload = build_cli_chat_request(
        text=question,
        team_id=team_id,
        channel_id=channel_id,
        thread_id=thread_id,
        user_id=user_id,
        sql_visibility_preference=_parse_sql_visibility_preference(show_sql, hide_sql),
    )
    response = handle_analytics_chat(payload)

    if json_output:
        click.echo(json.dumps(response.model_dump(mode="json"), indent=2))
        return

    render_cli_response(response, console=Console())
