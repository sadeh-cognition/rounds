## Development

Install and sync dependencies:

```bash
uv sync
```

Install Slack CLI and authenticate: <https://docs.slack.dev/tools/bolt-python/getting-started>

Start the provided Postgres database:

```bash
docker compose up -d db
```

Run tests against the local Postgres database:

```bash
uv run pytest
```

If another local Postgres is already using port 5432, start the project database
on a different host port and use the same port for Django commands:

```bash
POSTGRES_PORT=55432 docker compose up -d db
POSTGRES_PORT=55432 uv run manage.py migrate
POSTGRES_PORT=55432 uv run manage.py runserver 8001
POSTGRES_PORT=55432 uv run pytest
```

Run Django migrations for assistant metadata tables:

```bash
uv run manage.py migrate
```

Start the HTTP API on the expected port:

```bash
uv run manage.py runserver 8001
```

Start local Phoenix tracing:

```bash
uv run python -m phoenix.server.main serve
```

Run the Slack Socket Mode assistant process:

```bash
cd first-bolt-app
slack run
```

Follow this guide to set up Slack to work with the Slack CLI and create the agent: <https://docs.slack.dev/tools/bolt-python/getting-started>

In short:

- Have Slack workspace open in the default browser
- Install Slack CLI
- Authenticate with Slack CLI and the open workspace in your default browser
- Chat with app in Slack UI

## LLM Configuration

The analytics agent is configured entirely through environment variables.

### Required

| Variable | Description | Example |
|---|---|---|
| `LITELLM_MODEL` | LiteLLM provider/model identifier | `groq/llama-3.1-8b-instant` |

The format is `<provider>/<model-name>`, exactly as [LiteLLM expects](https://docs.litellm.ai/docs/providers).
Provider API keys are **not** managed by this setting — set them directly in the environment and LiteLLM resolves them automatically.

### Optional

| Variable | Default | Description |
|---|---|---|
| `ANALYTICS_SQL_REPAIR_RETRIES` | `2` | Number of times the agent retries a failed SQL generation/execution |

### Setup

1. Copy `.env.example` to `.env`.
2. Set `LITELLM_MODEL` and the corresponding provider API key:

**Groq**

```env
LITELLM_MODEL=groq/llama-3.1-8b-instant
GROQ_API_KEY=gsk_...
```

**OpenAI**

```env
LITELLM_MODEL=openai/gpt-4o
OPENAI_API_KEY=sk-...
```

**Anthropic**

```env
LITELLM_MODEL=anthropic/claude-3-5-sonnet-20241022
ANTHROPIC_API_KEY=sk-ant-...
```

If `LITELLM_MODEL` is missing or blank application startup fails.
