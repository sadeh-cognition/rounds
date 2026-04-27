# Portfolio Analytics Slack Assistant

This Slack app manifest is configured for the Django Socket Mode assistant in
`slack_assistant/management/commands/run_slack_assistant.py`.

## Environment

Set the Slack tokens created for this app:

```bash
export SLACK_BOT_TOKEN=<xoxb-bot-token>
export SLACK_APP_TOKEN=<xapp-app-level-token>
```

The assistant sends user messages to the local Django HTTP API. The default URL
is `http://localhost:8001`; override it only if the API runs elsewhere:

```bash
export ANALYTICS_API_BASE_URL=http://localhost:8001
```

## Run

From the repository root, start the Django API and the assistant process:

```bash
uv run manage.py runserver 8001
uv run manage.py run_slack_assistant
```

If the Slack CLI runs this app from `first-bolt-app/app.py`, that wrapper
delegates to the same `uv run manage.py run_slack_assistant` command.
