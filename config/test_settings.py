"""Settings used by the local pytest suite."""

import os

os.environ.setdefault("LITELLM_MODEL", "groq/llama-3.1-8b-instant")

from .settings import *  # noqa: F403


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    if "DATABASE_URL" in os.environ:
        TEST_DATABASE_URL = DATABASE_URL  # noqa: F405
    else:
        postgres_port = os.environ.get("POSTGRES_PORT", "5432")
        TEST_DATABASE_URL = (
            f"postgres://postgres:postgres@localhost:{postgres_port}/analytics"
        )

DATABASES = {
    "default": database_from_url(TEST_DATABASE_URL),  # noqa: F405
}
DATABASES["default"]["TEST"] = {
    "NAME": os.environ.get("TEST_DATABASE_NAME", "test_analytics"),
}

ANALYTICS_READONLY_DATABASE_URL = TEST_DATABASE_URL
