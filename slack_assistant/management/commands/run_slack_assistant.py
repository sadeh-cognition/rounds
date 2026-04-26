import django_click as click
from django.conf import settings
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler


@click.command()
def command() -> None:
    """Run the Slack AI Assistant bot in Socket Mode."""
    if not settings.SLACK_BOT_TOKEN:
        raise click.ClickException("SLACK_BOT_TOKEN is required.")
    if not settings.SLACK_APP_TOKEN:
        raise click.ClickException("SLACK_APP_TOKEN is required.")

    app = App(token=settings.SLACK_BOT_TOKEN)

    @app.event("app_mention")
    def handle_app_mention(body, say) -> None:
        say(
            text="The analytics assistant backend foundation is installed. "
            "The AI Assistant thread handler will be wired in the next feature slice.",
            thread_ts=body.get("event", {}).get("ts"),
        )

    SocketModeHandler(app, settings.SLACK_APP_TOKEN).start()
