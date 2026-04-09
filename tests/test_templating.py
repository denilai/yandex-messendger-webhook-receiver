from __future__ import annotations

import base64
import json

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app


def _basic(user: str, pwd: str) -> str:
    raw = f"{user}:{pwd}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


@respx.mock
def test_template_inline_is_used_for_text(alertmanager_payload, monkeypatch) -> None:
    monkeypatch.setenv("MESSAGE_TEMPLATE_INLINE", "[{{ payload.status|upper }}] {{ payload.groupKey }}")

    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    route = respx.post("https://botapi.messenger.yandex.net/bot/v1/messages/sendText").mock(
        return_value=httpx.Response(200, json={"ok": True, "message_id": 12})
    )

    client = TestClient(app)
    r = client.post(
        "/v1/alerts/users/alice",
        headers={"Authorization": _basic("user", "pass")},
        json=alertmanager_payload.model_dump(mode="json"),
    )
    assert r.status_code == 202
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    assert body["text"].startswith("[FIRING]")


@respx.mock
def test_broken_template_falls_back_to_default_format(alertmanager_payload, monkeypatch) -> None:
    monkeypatch.setenv("MESSAGE_TEMPLATE_INLINE", "{{ payload.no_such_attr.abc }}")

    from app.config import settings as settings_module

    settings_module.get_settings.cache_clear()

    route = respx.post("https://botapi.messenger.yandex.net/bot/v1/messages/sendText").mock(
        return_value=httpx.Response(200, json={"ok": True, "message_id": 13})
    )

    client = TestClient(app)
    r = client.post(
        "/v1/alerts/chats/123",
        headers={"Authorization": _basic("user", "pass")},
        json=alertmanager_payload.model_dump(mode="json"),
    )
    assert r.status_code == 202
    body = json.loads(route.calls.last.request.content.decode("utf-8"))
    # Default formatter produces header like "[FIRING]"
    assert body["text"].startswith("[FIRING]")

