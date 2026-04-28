from django.db import models


class TraceRecord(models.Model):
    trace_id = models.CharField(max_length=128, unique=True)
    conversation_id = models.PositiveBigIntegerField(null=True, blank=True)
    turn_id = models.PositiveBigIntegerField(null=True, blank=True)
    provider = models.CharField(max_length=64, blank=True)
    model = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.trace_id
