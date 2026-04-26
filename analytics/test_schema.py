from __future__ import annotations

from analytics.agent_tools import get_schema_context
from analytics.models import AnalyticsApp, DailyMetric
from analytics.schema import ALLOWED_TABLE_NAMES, get_analytics_schema_context


def test_unmanaged_models_map_seed_tables() -> None:
    assert AnalyticsApp._meta.managed is False
    assert AnalyticsApp._meta.db_table == "apps"
    assert DailyMetric._meta.managed is False
    assert DailyMetric._meta.db_table == "daily_metrics"


def test_schema_context_exposes_only_allowed_analytics_tables(settings) -> None:
    settings.ANALYTICS_INLINE_ROW_LIMIT = 25
    settings.ANALYTICS_MAX_ROW_LIMIT = 500

    context = get_analytics_schema_context()

    assert ALLOWED_TABLE_NAMES == ("apps", "daily_metrics")
    assert [table["name"] for table in context["allowed_tables"]] == [
        "apps",
        "daily_metrics",
    ]
    assert context["sql_rules"]["allowed_tables"] == ["apps", "daily_metrics"]
    assert "analytics_slackturn" in context["sql_rules"]["forbidden_tables"]
    assert context["row_limits"] == {"inline_rows": 25, "max_returned_rows": 500}


def test_schema_context_includes_column_meanings_relationships_and_utc_rule() -> None:
    context = get_analytics_schema_context(
        conversation_context={"last_user_question": "how many android apps?"}
    )

    daily_metrics = next(
        table for table in context["allowed_tables"] if table["name"] == "daily_metrics"
    )
    column_meanings = {
        column["name"]: column["meaning"] for column in daily_metrics["columns"]
    }

    assert daily_metrics["primary_key"] == ("app_id", "date", "country")
    assert "UTC calendar date" in column_meanings["date"]
    assert "ISO-3166 alpha-2" in column_meanings["country"]
    assert context["allowed_relationships"] == [
        {
            "from_table": "daily_metrics",
            "from_column": "app_id",
            "to_table": "apps",
            "to_column": "app_id",
            "meaning": "Each metric row belongs to exactly one portfolio app.",
        }
    ]
    assert "UTC calendar dates" in context["date_rule"]
    assert context["conversation_context"]["last_user_question"] == (
        "how many android apps?"
    )


def test_schema_context_calls_out_ambiguous_business_terms() -> None:
    context = get_analytics_schema_context()

    assert "in-app revenue" in context["ambiguous_terms"]["revenue"]
    assert "installs" in context["ambiguous_terms"]["popularity"]
    assert context["metric_definitions"]["total_revenue"] == (
        "in_app_revenue + ads_revenue"
    )


def test_smolagents_tool_returns_same_schema_context() -> None:
    context = get_schema_context.forward({"thread_ts": "123.456"})

    assert [table["name"] for table in context["allowed_tables"]] == [
        "apps",
        "daily_metrics",
    ]
    assert context["conversation_context"] == {"thread_ts": "123.456"}
