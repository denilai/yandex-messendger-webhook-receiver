from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.basic import require_basic_auth
from app.config.settings import Settings, get_settings
from app.models.alertmanager import AlertmanagerWebhookV4
from app.services.formatters import render_alertmanager_text
from app.services.yandex_client import (
    YandexClient,
    YandexPermanentError,
    YandexTemporaryError,
    build_payload_id,
)

router = APIRouter(prefix="/v1", tags=["alerts"])


def _client(settings: Settings) -> YandexClient:
    return YandexClient(settings)


def _accepted(ok: bool, message_id: int | None) -> dict[str, object]:
    return {"ok": ok, "yandex_message_id": message_id}


@router.post("/alerts/users/{login}", status_code=status.HTTP_202_ACCEPTED)
async def post_alerts_user(
    login: str,
    payload: AlertmanagerWebhookV4,
    _auth: None = Depends(require_basic_auth),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    text = render_alertmanager_text(payload)
    client = _client(settings)
    payload_id = build_payload_id(payload)

    try:
        res = await client.send_text(text=text, login=login, chat_id=None, payload_id=payload_id)
        return _accepted(True, res.message_id)
    except YandexTemporaryError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except YandexPermanentError as e:
        if settings.fail_on_yandex_4xx:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return _accepted(False, None)


@router.post("/alerts/chats/{chat_id}", status_code=status.HTTP_202_ACCEPTED)
async def post_alerts_chat(
    chat_id: str,
    payload: AlertmanagerWebhookV4,
    _auth: None = Depends(require_basic_auth),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    text = render_alertmanager_text(payload)
    client = _client(settings)
    payload_id = build_payload_id(payload)

    try:
        res = await client.send_text(text=text, login=None, chat_id=chat_id, payload_id=payload_id)
        return _accepted(True, res.message_id)
    except YandexTemporaryError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except YandexPermanentError as e:
        if settings.fail_on_yandex_4xx:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return _accepted(False, None)

