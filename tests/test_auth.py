from __future__ import annotations

import base64

import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.main import app


def _basic(user: str, pwd: str) -> str:
    raw = f"{user}:{pwd}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


@respx.mock
def test_auth_missing_returns_401_with_www_authenticate() -> None:
    client = TestClient(app)
    r = client.post("/v1/alerts/users/test", json={})
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers
    assert "Basic" in r.headers["WWW-Authenticate"]


@respx.mock
def test_auth_wrong_returns_401_with_www_authenticate() -> None:
    client = TestClient(app)
    r = client.post(
        "/v1/alerts/users/test",
        headers={"Authorization": _basic("user", "wrong")},
        json={},
    )
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers
    assert "Basic" in r.headers["WWW-Authenticate"]


@respx.mock
def test_auth_ok_allows_request_to_reach_handler_and_call_yandex() -> None:
    respx.post("https://botapi.messenger.yandex.net/bot/v1/messages/sendText").mock(
        return_value=Response(200, json={"ok": True, "message_id": 123})
    )

    client = TestClient(app)
    r = client.post(
        "/v1/alerts/users/test",
        headers={"Authorization": _basic("user", "pass")},
        json={
            "version": "4",
            "status": "firing",
            "groupKey": "g",
            "receiver": "r",
            "truncatedAlerts": 0,
            "groupLabels": {},
            "commonLabels": {},
            "commonAnnotations": {},
            "externalURL": None,
            "alerts": [],
        },
    )
    assert r.status_code == 202
    assert r.json()["ok"] is True
