from __future__ import annotations

from ninja import Router

from analytics.chat_schemas import AnalyticsChatRequest, AnalyticsChatResponse
from analytics.chat_service import handle_analytics_chat

router = Router(tags=["analytics"])


@router.post("/chat", response=AnalyticsChatResponse)
def analytics_chat(request, payload: AnalyticsChatRequest) -> AnalyticsChatResponse:
    return handle_analytics_chat(payload)
