from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import (
    AnalyticsApp,
    AnalyticsResultMetadata,
    GeneratedSQL,
    PendingClarification,
    SlackConversation,
    SlackTurn,
)


class ReadOnlyAdminMixin:
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: object | None = None,
    ) -> bool:
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: object | None = None,
    ) -> bool:
        return False


@admin.register(AnalyticsApp)
class AnalyticsAppAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("app_id", "name", "platform")
    list_filter = ("platform",)
    search_fields = ("app_id", "name", "platform")
    ordering = ("name", "platform")


class SlackTurnInline(admin.TabularInline):
    model = SlackTurn
    extra = 0
    fields = ("role", "slack_user_id", "slack_ts", "text", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


class PendingClarificationInline(admin.StackedInline):
    model = PendingClarification
    extra = 0
    fields = ("question", "context", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    can_delete = False

    def has_add_permission(
        self,
        request: HttpRequest,
        obj: SlackConversation | None,
    ) -> bool:
        if obj is None:
            return False
        return not hasattr(obj, "pending_clarification")


@admin.register(SlackConversation)
class SlackConversationAdmin(admin.ModelAdmin):
    list_display = ("team_id", "channel_id", "thread_ts", "created_at", "updated_at")
    list_filter = ("created_at", "updated_at")
    search_fields = ("team_id", "channel_id", "thread_ts", "turns__text")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-updated_at",)
    inlines = (PendingClarificationInline, SlackTurnInline)


class GeneratedSQLInline(admin.TabularInline):
    model = GeneratedSQL
    extra = 0
    fields = ("validation_status", "sql", "error", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


class AnalyticsResultMetadataInline(admin.StackedInline):
    model = AnalyticsResultMetadata
    extra = 0
    fields = (
        "row_count",
        "returned_row_count",
        "truncated",
        "columns",
        "csv_attachment_id",
        "sql_attachment_id",
        "created_at",
    )
    readonly_fields = ("created_at",)
    can_delete = False

    def has_add_permission(self, request: HttpRequest, obj: SlackTurn | None) -> bool:
        if obj is None:
            return False
        return not hasattr(obj, "result_metadata")


@admin.register(SlackTurn)
class SlackTurnAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "conversation",
        "role",
        "text",
        "slack_user_id",
        "slack_ts",
        "created_at",
    )
    list_filter = ("role", "created_at")
    search_fields = (
        "text",
        "slack_user_id",
        "slack_ts",
        "conversation__team_id",
        "conversation__channel_id",
        "conversation__thread_ts",
    )
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    inlines = (GeneratedSQLInline, AnalyticsResultMetadataInline)


@admin.register(PendingClarification)
class PendingClarificationAdmin(admin.ModelAdmin):
    list_display = ("conversation", "question", "created_at", "updated_at")
    list_filter = ("created_at", "updated_at")
    search_fields = ("question", "conversation__team_id", "conversation__channel_id")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-updated_at",)


@admin.register(GeneratedSQL)
class GeneratedSQLAdmin(admin.ModelAdmin):
    list_display = ("turn", "validation_status", "created_at")
    list_filter = ("validation_status", "created_at")
    search_fields = ("sql", "error", "turn__text")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


@admin.register(AnalyticsResultMetadata)
class AnalyticsResultMetadataAdmin(admin.ModelAdmin):
    list_display = (
        "turn",
        "row_count",
        "returned_row_count",
        "truncated",
        "created_at",
    )
    list_filter = ("truncated", "created_at")
    search_fields = ("turn__text", "csv_attachment_id", "sql_attachment_id")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    def get_queryset(
        self,
        request: HttpRequest,
    ) -> QuerySet[AnalyticsResultMetadata]:
        return (
            super().get_queryset(request).select_related("turn", "turn__conversation")
        )
