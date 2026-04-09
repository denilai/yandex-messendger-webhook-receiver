from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app


def _basic(user: str, pwd: str) -> str:
    raw = f"{user}:{pwd}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


@respx.mock
def test_users_endpoint_calls_yandex_and_sends_login(alertmanager_payload) -> None:
    route = respx.post("https://botapi.messenger.yandex.net/bot/v1/messages/sendText").mock(
        return_value=httpx.Response(200, json={"ok": True, "message_id": 10})
    )

    client = TestClient(app)
    r = client.post(
        "/v1/alerts/users/alice",
        headers={"Authorization": _basic("user", "pass")},
        json=alertmanager_payload.model_dump(mode="json"),
    )
    assert r.status_code == 202
    assert route.called
    sent = route.calls.last.request
    body = json.loads(sent.content.decode("utf-8"))
    assert body["login"] == "alice"
    assert "chat_id" not in body
    assert body["text"]
    assert body["payload_id"]


@respx.mock
def test_chats_endpoint_calls_yandex_and_sends_chat_id(alertmanager_payload) -> None:
    route = respx.post("https://botapi.messenger.yandex.net/bot/v1/messages/sendText").mock(
        return_value=httpx.Response(200, json={"ok": True, "message_id": 11})
    )

    client = TestClient(app)
    r = client.post(
        "/v1/alerts/chats/123",
        headers={"Authorization": _basic("user", "pass")},
        json=alertmanager_payload.model_dump(mode="json"),
    )
    assert r.status_code == 202
    assert route.called
    sent = route.calls.last.request
    body = json.loads(sent.content.decode("utf-8"))
    assert body["chat_id"] == "123"
    assert "login" not in body
    assert body["text"]
    assert body["payload_id"]


@respx.mock
def test_temporary_yandex_failure_maps_to_503(alertmanager_payload) -> None:
    respx.post("https://botapi.messenger.yandex.net/bot/v1/messages/sendText").mock(
        side_effect=httpx.ReadTimeout("timeout")
    )

    client = TestClient(app)
    r = client.post(
        "/v1/alerts/users/alice",
        headers={"Authorization": _basic("user", "pass")},
        json=alertmanager_payload.model_dump(mode="json"),
    )
    assert r.status_code == 503


@respx.mock
def test_permanent_yandex_4xx_maps_to_202_by_default(alertmanager_payload, monkeypatch) -> None:
    monkeypatch.setenv("FAIL_ON_YANDEX_4XX", "false")

    respx.post("https://botapi.messenger.yandex.net/bot/v1/messages/sendText").mock(
        return_value=httpx.Response(403, json={"ok": False, "description": "forbidden"})
    )

    client = TestClient(app)
    r = client.post(
        "/v1/alerts/users/alice",
        headers={"Authorization": _basic("user", "pass")},
        json=alertmanager_payload.model_dump(mode="json"),
    )
    assert r.status_code == 202


@respx.mock
def test_permanent_yandex_4xx_maps_to_422_when_fail_on_is_true(alertmanager_payload, monkeypatch) -> None:
    monkeypatch.setenv("FAIL_ON_YANDEX_4XX", "true")

    # Reload settings cache by importing module-level cache and clearing is handled by autouse fixture,
    # but here we override after; so we need to create a fresh TestClient after cache clear.
    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    respx.post("https://botapi.messenger.yandex.net/bot/v1/messages/sendText").mock(
        return_value=httpx.Response(400, json={"ok": False, "description": "bad request"})
    )

    client = TestClient(app)
    r = client.post(
        "/v1/alerts/users/alice",
        headers={"Authorization": _basic("user", "pass")},
        json=alertmanager_payload.model_dump(mode="json"),
    )
    assert r.status_code == 422

