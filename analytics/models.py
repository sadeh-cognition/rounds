from django.db import models


class AnalyticsApp(models.Model):
    app_id = models.TextField(primary_key=True)
    name = models.TextField()
    platform = models.TextField()

    class Meta:
        managed = False
        db_table = "apps"

    def __str__(self) -> str:
        return f"{self.name} ({self.platform})"


class DailyMetric(models.Model):
    pk = models.CompositePrimaryKey("app", "date", "country")
    app = models.ForeignKey(
        AnalyticsApp,
        db_column="app_id",
        on_delete=models.DO_NOTHING,
        related_name="daily_metrics",
    )
    date = models.DateField()
    country = models.CharField(max_length=2)
    installs = models.BigIntegerField()
    in_app_revenue = models.DecimalField(max_digits=12, decimal_places=2)
    ads_revenue = models.DecimalField(max_digits=12, decimal_places=2)
    ua_cost = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        managed = False
        db_table = "daily_metrics"

    def __str__(self) -> str:
        return f"{self.app_id} {self.date} {self.country}"


class SlackConversation(models.Model):
    team_id = models.CharField(max_length=64)
    channel_id = models.CharField(max_length=64)
    thread_ts = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "channel_id", "thread_ts"],
                name="unique_slack_conversation_thread",
            )
        ]

    def __str__(self) -> str:
        return f"{self.team_id}/{self.channel_id}/{self.thread_ts}"


class SlackTurn(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(
        SlackConversation,
        on_delete=models.CASCADE,
        related_name="turns",
    )
    role = models.CharField(max_length=16, choices=Role)
    slack_user_id = models.CharField(max_length=64, blank=True)
    slack_ts = models.CharField(max_length=64, blank=True)
    text = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.role}: {self.text[:80]}"


class PendingClarification(models.Model):
    conversation = models.OneToOneField(
        SlackConversation,
        on_delete=models.CASCADE,
        related_name="pending_clarification",
    )
    question = models.TextField()
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.question


class GeneratedSQL(models.Model):
    turn = models.ForeignKey(
        SlackTurn,
        on_delete=models.CASCADE,
        related_name="generated_sql",
    )
    sql = models.TextField()
    validation_status = models.CharField(max_length=32)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.validation_status}: {self.sql[:80]}"


class AnalyticsResultMetadata(models.Model):
    turn = models.OneToOneField(
        SlackTurn,
        on_delete=models.CASCADE,
        related_name="result_metadata",
    )
    row_count = models.PositiveIntegerField(default=0)
    returned_row_count = models.PositiveIntegerField(default=0)
    truncated = models.BooleanField(default=False)
    columns = models.JSONField(default=list, blank=True)
    csv_attachment_id = models.CharField(max_length=128, blank=True)
    sql_attachment_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.returned_row_count}/{self.row_count} rows"
