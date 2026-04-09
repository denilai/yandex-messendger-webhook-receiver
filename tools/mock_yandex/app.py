from __future__ import annotations

import os
import random
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request

app = FastAPI(title="mock-yandex", version="0.1.0")


@dataclass
class StoredRequest:
    method: str
    path: str
    headers: dict[str, str]
    json: dict[str, Any]


_requests: list[StoredRequest] = []
_max_keep = 200


def _mode() -> str:
    return os.getenv("MOCK_YANDEX_MODE", "always_ok")


def _maybe_fail() -> None:
    mode = _mode()
    if mode == "always_ok":
        return
    if mode == "always_500":
        raise HTTPException(status_code=500, detail="mock forced 500")
    if mode == "always_429":
        raise HTTPException(status_code=429, detail="mock forced 429")
    if mode == "random_500":
        p = float(os.getenv("MOCK_YANDEX_FAIL_PROB", "0.1"))
        if random.random() < p:  # noqa: S311 - test-only randomness is fine
            raise HTTPException(status_code=500, detail="mock random 500")
        return
    if mode == "random_429":
        p = float(os.getenv("MOCK_YANDEX_FAIL_PROB", "0.1"))
        if random.random() < p:  # noqa: S311 - test-only randomness is fine
            raise HTTPException(status_code=429, detail="mock random 429")
        return


@app.post("/bot/v1/messages/sendText")
async def send_text(req: Request) -> dict[str, Any]:
    _maybe_fail()

    body = await req.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid json")

    text = body.get("text")
    login = body.get("login")
    chat_id = body.get("chat_id")

    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    if bool(login) == bool(chat_id):
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

    message_id = len(_requests) + 1000
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
        "items": [{"method": r.method, "path": r.path, "headers": r.headers, "json": r.json} for r in items],
    }

