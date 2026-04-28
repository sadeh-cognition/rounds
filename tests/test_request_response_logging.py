from __future__ import annotations

import json
import logging

from django.test import Client


def test_request_and_json_response_are_logged(caplog) -> None:
    client = Client()
    logger = logging.getLogger("config.request_response")

    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="config.request_response")
    try:
        response = client.get("/api/health")
    finally:
        logger.removeHandler(caplog.handler)

    assert response.status_code == 200

    log_payloads = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "config.request_response"
    ]
    assert [payload["event"] for payload in log_payloads] == [
        "request_started",
        "response_completed",
    ]
    assert log_payloads[0] == {
        "event": "request_started",
        "method": "GET",
        "path": "/api/health",
    }
    assert log_payloads[1]["method"] == "GET"
    assert log_payloads[1]["path"] == "/api/health"
    assert log_payloads[1]["status_code"] == 200
    assert log_payloads[1]["response_json"] == {"status": "ok"}
    assert isinstance(log_payloads[1]["duration_ms"], float)
