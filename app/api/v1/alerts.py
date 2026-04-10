from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)

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
    logger.info("Webhook received: login=%s alerts=%d status=%s", login, len(payload.alerts), payload.status)
    text = render_alertmanager_text(payload, settings=settings)
    client = _client(settings)
    payload_id = build_payload_id(payload)

    try:
        res = await client.send_text(text=text, login=login, chat_id=None, payload_id=payload_id)
        logger.info("Message sent: login=%s message_id=%s", login, res.message_id)
        return _accepted(True, res.message_id)
    except YandexTemporaryError as e:
        logger.error("Yandex temporary error: login=%s %s", login, e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    except YandexPermanentError as e:
        if settings.fail_on_yandex_4xx:
            logger.error("Yandex permanent error: login=%s %s", login, e)
            raise HTTPException(status_code=422, detail=str(e)) from e
        logger.warning("Yandex permanent error (ignored): login=%s %s", login, e)
        return _accepted(False, None)


@router.post("/alerts/chats/{chat_id}", status_code=status.HTTP_202_ACCEPTED)
async def post_alerts_chat(
    chat_id: str,
    payload: AlertmanagerWebhookV4,
    _auth: None = Depends(require_basic_auth),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    logger.info("Webhook received: chat_id=%s alerts=%d status=%s", chat_id, len(payload.alerts), payload.status)
    text = render_alertmanager_text(payload, settings=settings)
    client = _client(settings)
    payload_id = build_payload_id(payload)

    try:
        res = await client.send_text(text=text, login=None, chat_id=chat_id, payload_id=payload_id)
        logger.info("Message sent: chat_id=%s message_id=%s", chat_id, res.message_id)
        return _accepted(True, res.message_id)
    except YandexTemporaryError as e:
        logger.error("Yandex temporary error: chat_id=%s %s", chat_id, e)
        raise HTTPException(status_code=503, detail=str(e)) from e
    except YandexPermanentError as e:
        if settings.fail_on_yandex_4xx:
            logger.error("Yandex permanent error: chat_id=%s %s", chat_id, e)
            raise HTTPException(status_code=422, detail=str(e)) from e
        logger.warning("Yandex permanent error (ignored): chat_id=%s %s", chat_id, e)
        return _accepted(False, None)

