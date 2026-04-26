from ninja import NinjaAPI

api = NinjaAPI(title="Slack Analytics Assistant API")


@api.get("/health")
def health(request) -> dict[str, str]:
    return {"status": "ok"}
