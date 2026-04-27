from ninja import NinjaAPI

from analytics.api import router as analytics_router

api = NinjaAPI(title="Slack Analytics Assistant API")
api.add_router("/analytics", analytics_router)


@api.get("/health")
def health(request) -> dict[str, str]:
    return {"status": "ok"}
