from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    name = "analytics"

    def ready(self) -> None:
        from analytics.llm import configure_analytics_llm

        configure_analytics_llm()
