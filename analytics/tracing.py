from django.conf import settings


def configure_phoenix_tracing() -> None:
    """Register Phoenix/OpenTelemetry instrumentation before agent execution."""
    import phoenix.otel
    from openinference.instrumentation.smolagents import SmolagentsInstrumentor

    phoenix.otel.register(project_name=settings.PHOENIX_PROJECT_NAME)
    SmolagentsInstrumentor().instrument()
