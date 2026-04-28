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

If `LITELLM_MODEL` is missing or blank the application raises an `AnalyticsLLMConfigurationError` on startup.

# Objective

Build a Slack chatbot for data analytics and business intelligence that can answer questions about
an apps portfolio.
The chatbot works with an SQL database, converting user questions into SQL statements, executing them, and providing users with interpreted, formatted data.
It should determine when to display a simple interpretation of the results and when to show the raw data, and support follow-up questions that build on earlier turns.
The chatbot should be powered by an agent that uses a LLM. Use `smolagents` for this purpose.

# Requirements

## Database

A Postgres instance with a ready-made schema and deterministic seed data is provided in this repo
(docker-compose.yml + db/init/). Please use it as-is.

The two tables in the analytics database:
• apps(app_id, name, platform) – 50 mobile apps. app_id is the store-facing identifier: the package
name for Android apps (e.g. com.rounds.paint) and the App Store numeric id as a string for iOS
apps. platform is either iOS or Android; each app exists on exactly one platform.
• daily_metrics(app_id, date, country, installs, in_app_revenue, ads_revenue, ua_cost) one row per app/day/country across ~40 countries and a 2-year window. app_id references
apps.app_id. in_app_revenue, ads_revenue, and ua_cost are monetary values; installs is a
count.
Country values are ISO-3166 alpha-2 codes (e.g. US, GB, JP).

# Question Answering

The chatbot handles a wide range of data requests while maintaining a natural conversational flow that allows for follow-up questions. It intelligently interprets user intent and provides responses with an appropriate level of detail.
It processes natural language queries related to the app portfolio and provides responses either in plain text or as detailed tables, depending on query complexity. If required details are missing, it asks a clarifying question before answering.
Users can ask follow-up questions within the same Slack thread, and the conversation context is
maintained across turns.
The chatbot uses a LLM for natural language understanding and SQL generation, ensuring that the generated SQL is syntactically correct and optimized for performance. It also includes error handling to manage invalid queries gracefully. Use litellm here.

# Observability and Traceability

Wire up observability / tracing for the agent so we can x-ray the inner workings of a live call during the presentation. Use a local Arize setup here.
Use this guide to set up telemetry: <https://huggingface.co/docs/smolagents/tutorials/inspect_runs>

# Slack Integration

The chatbot must run within Slack - you can use a free Developer Sandbox (<https://docs.slack.dev/tools/developer-sandboxes>) for testing. It is recommended to utilise Slack features such as AI Assistants(<https://slack.dev/resource-library/solution-ai-agents-assistants/>) and Code Snippets(<https://slack.com/intl/en-gb/help/articles/204145658-Create-or-paste-code-snippets-in-Slack>).

# Example User Questions and Chatbot Answers

Total app count.
user: how many apps do we have?
bot: [simple answer without a table]
Per-platform count with follow-up.
user: how many android apps do we have?
bot: [simple answer without a table]
user: what about ios?
bot: [follow-up answer showing the bot understood the question]
Daily installs with country follow-up.
user: how many installs did we get yesterday?
bot: [single number, plain text]
user: and in the US only?
bot: [follow-up number, showing the country filter was understood]
More complex questions
Revenue leaders by country.
user: which countries generate the most revenue?
bot: [table with country name and total revenue]
[asks a clarification first if the timeframe is missing]
iOS apps ranked by popularity.
user: List all ios apps sorted by their popularity
bot: [table of iOS apps sorted by popularity]
[explanation of how 'popularity' was defined]
Top 5 apps by ad revenue.
user: what were the top 5 apps by ad revenue last month?
bot: [short total + bullet list of the 5 apps with their ad revenue]
Month-over-month UA-spend change.
user: Which apps had the biggest change in UA spend comparing Jan 2025 to Dec 2024?
bot: [table showing apps with largest UA spend changes]
[optionally with extra columns for added context]

# Project Description

# Slack Analytics Assistant

## Summary

Build a Django + django-ninja backend and a Slack AI Assistant bot that answers portfolio analytics questions by generating and executing read-
only SQL against the provided Postgres dataset. The Slack bot runs via Bolt for Python Socket Mode and calls the backend HTTP API. The
smolagents agent uses ToolCallingAgent with LiteLLMModel; the model is fully env-configured with no hard-coded provider default.

Key decisions locked:

- Slack surface: AI Assistant threads only, Socket Mode.
- Dates: UTC calendar-relative dates.
- Ambiguous terms: ask a free-text clarification first.
- Raw data: allow read-only SQL, with 25 inline rows and 500 max returned rows.
- SQL visibility: attach .sql snippets only when requested or useful after failure.
- Metadata: persist conversations/turns in Django tables in the same Postgres database.
- Observability: full local Phoenix/Arize traces for prompts, tool calls, SQL, row counts, and final metadata.

## Key Changes

- Create a Django project with:
  - django-ninja API, served on port 8001.
  - Django models for Slack conversations, turns, pending clarifications, generated SQL, result metadata
  - Unmanaged models or SQLAlchemy/introspection helpers for the existing apps and daily_metrics tables; do not modify provided seed tables.
- Add POST /api/analytics/chat:
  - Request includes Slack team/channel/thread/user IDs, user text, UTC timestamp, and SQL visibility preference.
  - Response includes message text, optional table rows, optional CSV/SQL snippet payloads, and clarification state
- Add a Slack management command:
  - uv run manage.py run_slack_assistant
  - Uses Bolt Assistant middleware + Socket Mode.
  - Sends user messages to the backend HTTP API, then posts formatted Slack replies/snippets.
- Add Phoenix tracing command/docs:
  - uv run python -m phoenix.server.main serve
  - Initialize phoenix.otel.register() and SmolagentsInstrumentor().instrument() before agent execution.

## Agent And SQL Design

- Use smolagents.ToolCallingAgent with a LiteLLMModel configured from env, for example:
  - LITELLM_MODEL
  - provider-specific API keys such as GROQ_API_KEY, OPENAI_API_KEY, etc.
  - ANALYTICS_SQL_REPAIR_RETRIES, defaulting to a configurable positive integer.
- Agent tools:
  - get_schema_context: returns only the allowed analytics schema, column meanings, UTC date rule, row limits, and conversation context.
  - run_readonly_sql: validates SQL, enforces read-only access, executes it, and returns columns/rows/truncation metadata.
  - format_result_contract: converts results into a structured response contract for Slack.
- SQL safety layers:
  - Parse/validate with a SQL parser such as sqlglot.
  - Allow only read-only SELECT/CTE queries.
  - Allow only apps and daily_metrics.
  - Reject DDL, DML, multiple statements, comments used for injection, unsafe functions, and metadata-table access.
  - Execute with statement timeout, read-only transaction mode, and a read-only DB URL when configured.
  - Enforce 500 max rows, showing only 25 inline.
- No hidden “availability” queries on no-data cases. The bot interprets only the SQL result it requested.

## Conversation Behavior

- Follow-ups are resolved from persisted Slack thread context and prior turns.
- If a term is ambiguous, the bot asks a free-text clarification and stores pending clarification state.
  - Example: “which countries generate the most revenue?” should ask which revenue definition the user wants.
  - Example: “popularity” should ask whether popularity means installs, revenue, active countries, or another metric.
- Simple scalar results return plain text.
- Multi-row results return a concise summary plus a Slack-friendly table.
- Large/raw results attach CSV snippets; requested SQL attaches .sql snippets.
- SQL failure flow:
  - Validate before execution.
  - If validation/execution fails, retry up to ANALYTICS_SQL_REPAIR_RETRIES.
  - If still failing, return a concise explanation

## Test Plan

- Unit tests:
  - SQL validator accepts valid read-only joins/aggregations and rejects writes, multiple statements, forbidden tables, and unsafe queries.
  - Result formatter chooses plain text, inline table, CSV snippet, and SQL snippet correctly.
  - Conversation memory resolves Slack thread follow-ups and pending clarifications.
- API tests with django-ninja TestClient:
  - Validate request/response schemas using the ninja/Pydantic schemas.
  - Cover clarification response, SQL-on-request flag, row truncation metadata, and graceful errors.
- Live LLM tests:
  - Mark separately, gated by env such as RUN_LIVE_LLM_TESTS=1.
  - Use Groq llama-3.1-8b-instant when LLM tests run, per repo guidance.
  - Cover the supplied sample prompts, adjusted for strict clarification behavior.
- Manual demo checks:
  - Start Postgres, Django API, Phoenix, and Slack assistant process.
  - Ask scalar, follow-up, table, raw-data, clarification, SQL-on-request, and SQL-error-repair questions.
  - Confirm Phoenix shows the full agent trace.

## Implementation Notes

- The provided apps and daily_metrics tables remain unchanged.
- Django may add its own metadata tables to the same Postgres database.
- The SQL execution role should be read-only in real/demo config, but local development may initially use the provided Postgres credentials.
- Docker is required by the provided database setup, though this environment currently did not have the docker command available.
- References used: smolagents telemetry/Phoenix guide, smolagents Text-to-SQL example, smolagents LiteLLMModel docs, Slack Bolt Assistant
  middleware, Slack Socket Mode docs, Slack snippets docs.

## List of Features

Here is an ordered feature list extracted from the plan.

### Project Foundation

- Create Django project and apps.
- Use uv for dependencies and commands.
- Add django-ninja, pytest-django, slack-bolt, slack-sdk, smolagents, litellm, Phoenix/OpenTelemetry packages, Postgres driver, and SQL parser.
- Configure Django to run on port 8001.

### Database Configuration

- Use the provided Postgres database as-is.
- Keep existing apps and daily_metrics tables unchanged.
- Store Django metadata tables in the same Postgres database.
- Support a read-only analytics DB URL/role via env, while allowing local dev with provided credentials.

### Analytics Schema Access

- Represent apps and daily_metrics as unmanaged Django models or SQL/introspection helpers.
- Expose schema context to the agent:
  - table names
  - columns
  - column meanings
  - allowed relationships
  - UTC date rule
  - result row limits

### Conversation Persistence

- Add Django models for:
  - Slack conversation/thread identity
  - user turns
  - assistant turns
  - pending clarifications
  - generated SQL
  - result metadata
- Persist context per Slack thread for follow-up questions.

### Backend Chat API

- Add POST /api/analytics/chat using django-ninja.
- Request includes:
  - Slack team ID
  - channel ID
  - thread ID
  - user ID
  - user message text
  - UTC timestamp
  - SQL visibility preference
- Response includes:
  - Slack-ready text
  - optional table rows
  - optional CSV snippet payload
  - optional SQL snippet payload
  - clarification state

### LLM Configuration

- Use smolagents with LiteLLMModel.
- Require model/provider configuration from env.
- No hard-coded default provider.
- Support env vars such as:
  - LITELLM_MODEL
  - provider API keys
  - ANALYTICS_SQL_REPAIR_RETRIES

### Agent Core

- Use ToolCallingAgent.
- Add agent tools:
  - get_schema_context
  - run_readonly_sql
  - format_result_contract
- Agent handles:
  - natural language interpretation
  - SQL generation
  - follow-up context
  - result interpretation
  - clarification decisions

### Ambiguity Handling

- Ask free-text clarification before answering ambiguous business terms.
- Ambiguous examples include:
  - “revenue”
  - “popularity”
  - “biggest change”
- Store pending clarification state.
- Resolve the pending turn from the user’s next reply.

1. UTC Date Handling
      - Interpret relative dates using UTC calendar dates.
      - Examples:
          - “yesterday”
          - “last month”
          - “Jan 2025”
      - Do not switch to data-relative dates.
2. SQL Safety And Validation

- Validate generated SQL before execution.
- Allow only read-only SELECT and CTE queries.
- Allow only apps and daily_metrics.
- Reject:
  - DDL
  - DML
  - multiple statements
  - forbidden tables
  - unsafe functions
  - metadata-table access
  - injection-style comments or constructs
- Execute with:
  - read-only transaction mode
  - statement timeout
  - row cap enforcement

  1. SQL Execution

- Execute valid SQL against Postgres.
- Return structured result data:
  - columns
  - rows
  - row count
  - truncation metadata
- Allow raw read-only data requests.
- Show up to 25 rows inline.
- Return at most 500 rows total.
- Do not run hidden fallback/availability queries for no-data cases.

  1. SQL Repair Flow

- Retry failed SQL generation/execution up to configurable ANALYTICS_SQL_REPAIR_RETRIES.
- Retry covers validation or execution failures.
- After retries are exhausted, return a concise user-facing failure.

  1. Result Formatting

- Return simple scalar answers as plain text.
- Return multi-row results as summary plus Slack-friendly table.
- Return large/raw results as CSV snippets.
- Include SQL as .sql snippet only when requested or useful after failure.
- Include clarification notes where applicable.

### Slack Assistant Integration

- Add Django management command:
  - uv run manage.py run_slack_assistant
- Use Bolt for Python.
- Use Slack AI Assistant middleware.
- Use Socket Mode.
- Support Assistant threads only.
- Send Slack user messages to the backend HTTP API.
- Post backend responses back to Slack.

  1. Slack Snippet Support

- Upload CSV snippets for large result sets.
- Upload .sql snippets when SQL is requested.
- Keep inline messages concise.

  1. Observability And Tracing

- Add Phoenix/Arize local tracing setup.
- Initialize:
  - phoenix.otel.register()
  - SmolagentsInstrumentor().instrument()
- Trace:
  - prompts
  - tool calls
  - generated SQL
  - row counts
  - final answer metadata
  - errors
- Document Phoenix startup:
  - uv run python -m phoenix.server.main serve

  1. Backend API Tests

- Use django-ninja TestClient.
- Test request/response schemas.
- Test clarification responses.
- Test SQL-on-request behavior.
- Test row truncation metadata.
- Test graceful error responses.

  1. SQL Validator Tests

- Test valid read-only joins and aggregations.
- Test rejection of writes, multiple statements, forbidden tables, and unsafe SQL.
- Test row cap behavior.

  1. Conversation Tests

- Test Slack thread follow-up resolution.
- Test pending clarification storage and resolution.
- Test contextual follow-ups like “what about iOS?” and “in the US only?”

  1. Formatter Tests

- Test scalar answer formatting.
- Test inline table formatting.
- Test CSV snippet generation.
- Test SQL snippet generation.

  1. Live LLM Tests

- Add separately marked live tests.
- Gate behind env such as RUN_LIVE_LLM_TESTS=1.
- Use Groq llama-3.1-8b-instant when live LLM tests run.
- Cover the supplied sample prompts, adjusted for strict clarification behavior.

  1. Demo Documentation

- Document how to run:
  - Postgres
  - Django API
  - Phoenix
  - Slack assistant command
- Document required env vars.
- Document Slack sandbox setup.
- Document demo questions and expected behavior.
