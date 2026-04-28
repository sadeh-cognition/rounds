from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any, cast

from django.http import HttpRequest
from django.http.response import HttpResponseBase

logger = logging.getLogger("config.request_response")


class RequestResponseLoggingMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        started_at = time.monotonic()
        logger.info(
            json.dumps(
                {
                    "event": "request_started",
                    "method": request.method,
                    "path": request.get_full_path(),
                }
            )
        )

        response = self.get_response(request)

        log_payload: dict[str, Any] = {
            "event": "response_completed",
            "method": request.method,
            "path": request.get_full_path(),
            "status_code": response.status_code,
            "duration_ms": round((time.monotonic() - started_at) * 1000, 2),
        }
        response_json = self._response_json(response)
        if response_json is not None:
            log_payload["response_json"] = response_json

        logger.info(json.dumps(log_payload, default=str))
        return response

    def _response_json(self, response: HttpResponseBase) -> object | None:
        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type.lower():
            return None
        if getattr(response, "streaming", False):
            return None

        response_with_content = cast(Any, response)
        try:
            content = response_with_content.content
        except AttributeError:
            return None
        if not content:
            return None

        try:
            charset = response_with_content.charset or "utf-8"
            return json.loads(content.decode(charset))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning(
                json.dumps(
                    {
                        "event": "response_json_decode_failed",
                        "status_code": response.status_code,
                    }
                )
            )
            return None
