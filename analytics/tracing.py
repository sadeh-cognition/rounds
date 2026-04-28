from __future__ import annotations

import logging

from django.conf import settings


logger = logging.getLogger(__name__)
_configured = False


def configure_phoenix_tracing() -> None:
    """Register Phoenix/OpenTelemetry instrumentation before agent execution."""
    global _configured
    if _configured:
        return

    import phoenix.otel
    from openinference.instrumentation.smolagents import SmolagentsInstrumentor

    phoenix.otel.register(project_name=settings.PHOENIX_PROJECT_NAME)
    try:
        SmolagentsInstrumentor().instrument()
    except AttributeError as exc:
        logger.warning("Could not instrument smolagents for tracing: %s", exc)
    _configured = True
