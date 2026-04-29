from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from django.conf import settings


@dataclass(frozen=True)
class AnalyticsColumn:
    name: str
    type: str
    meaning: str


@dataclass(frozen=True)
class AnalyticsRelationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    meaning: str


@dataclass(frozen=True)
class AnalyticsTable:
    name: str
    meaning: str
    primary_key: tuple[str, ...]
    columns: tuple[AnalyticsColumn, ...]


APPS_TABLE = AnalyticsTable(
    name="apps",
    meaning="One row per mobile app in the portfolio.",
    primary_key=("app_id",),
    columns=(
        AnalyticsColumn(
            name="app_id",
            type="text",
            meaning=(
                "Store-facing app identifier. Android apps use package names; "
                "iOS apps use App Store numeric IDs stored as text."
            ),
        ),
        AnalyticsColumn(
            name="name",
            type="text",
            meaning="Human-readable app name.",
        ),
        AnalyticsColumn(
            name="platform",
            type="text",
            meaning="Mobile platform. Values are exactly 'iOS' or 'Android'.",
        ),
    ),
)

DAILY_METRICS_TABLE = AnalyticsTable(
    name="daily_metrics",
    meaning="One row per app, UTC calendar date, and ISO country code.",
    primary_key=("app_id", "date", "country"),
    columns=(
        AnalyticsColumn(
            name="app_id",
            type="text",
            meaning="App identifier. Join to apps.app_id.",
        ),
        AnalyticsColumn(
            name="date",
            type="date",
            meaning="UTC calendar date for the metric row.",
        ),
        AnalyticsColumn(
            name="country",
            type="char(2)",
            meaning="ISO-3166 alpha-2 country code, for example US, GB, or JP.",
        ),
        AnalyticsColumn(
            name="installs",
            type="bigint",
            meaning="Number of app installs for the app/date/country.",
        ),
        AnalyticsColumn(
            name="in_app_revenue",
            type="numeric(12,2)",
            meaning="Revenue from in-app purchases for the app/date/country.",
        ),
        AnalyticsColumn(
            name="ads_revenue",
            type="numeric(12,2)",
            meaning="Advertising revenue for the app/date/country.",
        ),
        AnalyticsColumn(
            name="ua_cost",
            type="numeric(12,2)",
            meaning="User-acquisition spend for the app/date/country.",
        ),
    ),
)

ALLOWED_ANALYTICS_TABLES = (APPS_TABLE, DAILY_METRICS_TABLE)
ALLOWED_TABLE_NAMES = tuple(table.name for table in ALLOWED_ANALYTICS_TABLES)

ALLOWED_RELATIONSHIPS = (
    AnalyticsRelationship(
        from_table="daily_metrics",
        from_column="app_id",
        to_table="apps",
        to_column="app_id",
        meaning="Each metric row belongs to exactly one portfolio app.",
    ),
)

METRIC_DEFINITIONS = {
    "total_revenue": "in_app_revenue + ads_revenue",
    "profit": "in_app_revenue + ads_revenue - ua_cost",
    "roas": "(in_app_revenue + ads_revenue) / ua_cost when ua_cost is non-zero",
}


def get_analytics_schema_context(
    conversation_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the only schema context the analytics agent is allowed to use."""
    return {
        "allowed_tables": [asdict(table) for table in ALLOWED_ANALYTICS_TABLES],
        "allowed_relationships": [
            asdict(relationship) for relationship in ALLOWED_RELATIONSHIPS
        ],
        "metric_definitions": METRIC_DEFINITIONS,
        "date_rule": (
            "Interpret relative dates using UTC calendar dates. Do not use local "
            "Slack user time zones unless a later feature explicitly provides one."
        ),
        "sql_rules": {
            "allowed_statement_types": ["SELECT", "WITH"],
            "allowed_tables": list(ALLOWED_TABLE_NAMES),
            "forbidden_tables": [
                "analytics_slackconversation",
                "analytics_slackturn",
                "analytics_pendingclarification",
                "analytics_generatedsql",
                "analytics_analyticsresultmetadata",
                "django_migrations",
                "auth_user",
            ],
            "no_hidden_availability_queries": True,
        },
        "row_limits": {
            "inline_rows": settings.ANALYTICS_INLINE_ROW_LIMIT,
            "max_returned_rows": settings.ANALYTICS_MAX_ROW_LIMIT,
        },
        "conversation_context": conversation_context or {},
    }
