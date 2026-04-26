# AGENTS

## python-env-manager.md

Use `uv` to manage the python environment.
Use `uv` to manage python package dependencies: e.g. `uv add requests` instead of `pip install requests`.
Use `uv` to envoke python commands.

## tech-stack.md

To create CLI commands use `django-click`. `django-click` is documented here: <https://github.com/django-commons/django-click>
For the TUI user interface use the `rich` python package.
For the front-end use HTMX and Tailwind CSS.
The backend is a Django HTTP API implemented using `django-ninja`.
When interacting with the backend, always use the HTTP API.
Always use the HTTP API for fetching, updating, or deleting data.
When writing Django code, try your hardest not to use Django signals.

## llm-interactions.md

When interacting with a LLM use litellm with structured outputs. Define output types using Pydantic models. For agentic flows use the `smolagents` Python package.

## ui-backend-interactions.md

All UI/TUI interactions with data should be done via the backend HTTP API.
In the TUI, all business logic should be extracted into functions which can be used without the TUI. This will improve testability and separation of concerns.
In the TUI, When calling the backend API reuse the ninja schemas that define the endpoint's request payload type. Also, reuse the response schema to parse the response from the HTTP API. The goal is to ensure the shape of data sent to the backend and returned from the backend is consistent across the application and to avoid writing duplicate code for parsing and validating data.

## test-tools.md

For testing use the `pytest-django` package documented here: <https://pytest-django.readthedocs.io/en/latest/>
When creating fixtures that involve Django ORM models use the `model-bakery` package documented here: <https://github.com/model-bakers/model_bakery>
When testing the Django admin use `curl` command instead of the browser agent.
When testing involves using LLMs use the "groq" provider and model name "llama-3.1-8b-instant".
Do not use ollama in tests.

## endpoint-tests

Whenever you create a new endpoint or modify an existing one make sure the endpoint is tested functionally.
To test the endpoint use the TestClient of the django-ninja package.
For fixtures and test dependencies use pytest fixtures.
In tests that call the backend API use the ninja schemas that define the endpoints incoming request type. Also, use the response schema to parse the response from the HTTP API.
Do not use any mocks.
Do not monkeypatch anything.

## graphdb.md

To store data in a graph database use ladybugdb documented here: <https://docs.ladybugdb.com/tutorials/python/>

## http-api.md

Use django-ninja for creating HTTP APIs.
django-ninja docs are here: <https://django-ninja.dev/>

## running-backend-server.md

To run the backend Django server use this command:
`uv run manage.py runserver 8001`

Note: the port number is 8001

## type-hints.md

Use type hints even when writing Django code. Use this package <https://github.com/typeddjango/django-stubs> for type hinting Django code.

## vector-db.md

Use ChromaDB as vector db. Docs are here: <https://docs.trychroma.com/docs/overview/getting-started>
Use Chromadb for vector and text search features.
Do not monkeypatch Chroma in tests.
To create embeddings use the local LMStudio server I have running in my environment.
The embedding model and provider are configured in the `EmbeddingModelConfig` table.
