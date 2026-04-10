from __future__ import annotations

import os
import random
import time
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

app = FastAPI(title="mock-yandex", version="0.1.0")
logger = logging.getLogger(__name__)


@dataclass
class StoredRequest:
    method: str
    path: str
    headers: dict[str, str]
    json: dict[str, Any]


_requests: list[StoredRequest] = []
_max_keep = 200
_total_requests = 0

SEND_TEXT_TOTAL = Counter(
    "mock_yandex_send_text_total",
    "Total accepted sendText requests.",
)
SEND_TEXT_FAILURES_TOTAL = Counter(
    "mock_yandex_send_text_failures_total",
    "sendText errors by reason.",
    ["reason"],
)
SEND_TEXT_LATENCY_SECONDS = Histogram(
    "mock_yandex_send_text_latency_seconds",
    "Latency of mock sendText handler.",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1),
)
STORED_REQUESTS_GAUGE = Gauge(
    "mock_yandex_stored_requests",
    "Number of request items currently stored in ring buffer.",
)


def _mode() -> str:
    return os.getenv("MOCK_YANDEX_MODE", "always_ok")


def _maybe_fail() -> None:
    mode = _mode()
    if mode == "always_ok":
        return
    if mode == "always_500":
        SEND_TEXT_FAILURES_TOTAL.labels(reason="always_500").inc()
        raise HTTPException(status_code=500, detail="mock forced 500")
    if mode == "always_429":
        SEND_TEXT_FAILURES_TOTAL.labels(reason="always_429").inc()
        raise HTTPException(status_code=429, detail="mock forced 429")
    if mode == "random_500":
        p = float(os.getenv("MOCK_YANDEX_FAIL_PROB", "0.1"))
        if random.random() < p:  # noqa: S311 - test-only randomness is fine
            SEND_TEXT_FAILURES_TOTAL.labels(reason="random_500").inc()
            raise HTTPException(status_code=500, detail="mock random 500")
        return
    if mode == "random_429":
        p = float(os.getenv("MOCK_YANDEX_FAIL_PROB", "0.1"))
        if random.random() < p:  # noqa: S311 - test-only randomness is fine
            SEND_TEXT_FAILURES_TOTAL.labels(reason="random_429").inc()
            raise HTTPException(status_code=429, detail="mock random 429")
        return


@app.post("/bot/v1/messages/sendText")
async def send_text(req: Request) -> dict[str, Any]:
    start = time.perf_counter()
    global _total_requests  # noqa: PLW0603 - test utility in-memory counter
    _maybe_fail()

    body = await req.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid json")

    text = body.get("text")
    login = body.get("login")
    chat_id = body.get("chat_id")

    if not isinstance(text, str) or not text.strip():
        SEND_TEXT_FAILURES_TOTAL.labels(reason="validation").inc()
        raise HTTPException(status_code=400, detail="text is required")
    if bool(login) == bool(chat_id):
        SEND_TEXT_FAILURES_TOTAL.labels(reason="validation").inc()
        raise HTTPException(status_code=400, detail="exactly one of login/chat_id is required")

    stored = StoredRequest(
        method=req.method,
        path=str(req.url.path),
        headers={k.lower(): v for k, v in req.headers.items()},
        json=body,
    )
    _requests.append(stored)
    if len(_requests) > _max_keep:
        del _requests[:-_max_keep]
    _total_requests += 1
    STORED_REQUESTS_GAUGE.set(len(_requests))
    SEND_TEXT_TOTAL.inc()
    SEND_TEXT_LATENCY_SECONDS.observe(time.perf_counter() - start)

    message_id = len(_requests) + 1000
    logger.info(
        "Mock delivered: payload_id=%s message_id=%s target=%s",
        body.get("payload_id"),
        message_id,
        "user" if login else "chat",
    )
    return {"ok": True, "message_id": message_id}


@app.get("/_last")
async def last() -> dict[str, Any]:
    if not _requests:
        return {"ok": True, "request": None}
    r = _requests[-1]
    return {"ok": True, "request": {"method": r.method, "path": r.path, "headers": r.headers, "json": r.json}}


@app.get("/_requests")
async def requests_list(limit: int = 20) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    items = _requests[-limit:]
    return {
        "ok": True,
        "count": len(_requests),
        "total_requests": _total_requests,
        "items": [{"method": r.method, "path": r.path, "headers": r.headers, "json": r.json} for r in items],
    }


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

